from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils.people_loader import load_people_notes_with_report
from obsidian_ai_hub.utils.periods import periods_overlap
from obsidian_ai_hub.summary.store import normalize_entity_name
from obsidian_ai_hub.web.services.person_relations import (
    preview_person_relation_merge,
    transfer_person_relations_on_merge,
)
from obsidian_ai_hub.web.services.person_properties import (
    preview_person_property_merge,
    transfer_person_properties_on_merge,
    JST,
)

logger = logging.getLogger(__name__)


def merge_display_orders(order1: int | None, order2: int | None) -> int | None:
    if order1 is None and order2 is None:
        return None
    if order1 is None:
        return order2
    if order2 is None:
        return order1
    return min(order1, order2)


def _consolidate_single_cardinality_items(
    item_list: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge same-valued items with overlapping validity periods.

    Groups items by typed value and merges overlapping ranges within each
    group (None means unbounded). Distinct values are preserved as-is so
    non-overlapping history is retained.
    """
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    group_order: list[tuple[Any, ...]] = []
    for item in item_list:
        key = (
            item.get("value_text"),
            item.get("value_date"),
            item.get("value_number"),
            item.get("value_boolean"),
            item.get("option_id"),
        )
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(item)

    consolidated: list[dict[str, Any]] = []
    for key in group_order:
        items = sorted(
            groups[key],
            key=lambda it: (it.get("valid_from") is not None, it.get("valid_from") or ""),
        )
        merged: list[dict[str, Any]] = []
        for item in items:
            current = dict(item)
            if not merged:
                merged.append(current)
                continue
            last = merged[-1]
            if periods_overlap(
                last.get("valid_from"),
                last.get("valid_until"),
                current.get("valid_from"),
                current.get("valid_until"),
            ):
                ls, le = last.get("valid_from"), last.get("valid_until")
                cs, ce = current.get("valid_from"), current.get("valid_until")
                last["valid_from"] = (
                    None if ls is None or cs is None else min(ls, cs)
                )
                last["valid_until"] = (
                    None if le is None or ce is None else max(le, ce)
                )
            else:
                merged.append(current)
        consolidated.extend(merged)
    return consolidated


def get_db_vault_conflicts_report(
    conn: sqlite3.Connection, parsed_notes: list[dict]
) -> dict[str, list[dict]]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT normalized_name, person_id, display_name FROM person_aliases"
    )
    aliases_rows = cursor.fetchall()

    cursor.execute("SELECT person_id, vault_id, display_name FROM people")
    people_rows = cursor.fetchall()
    people_map = {
        r["person_id"]: (r["vault_id"], r["display_name"]) for r in people_rows
    }

    mismatches = []
    compound_conflicts = []

    for row in aliases_rows:
        alias_norm = row["normalized_name"]
        db_person_id = row["person_id"]
        db_person_vault_id, db_person_display_name = people_map.get(
            db_person_id, (None, row["display_name"])
        )

        # Find all claimants of this alias in the Vault notes
        vault_claimers = []
        for note in parsed_notes:
            note_name_norm = normalize_entity_name(note["name"])
            note_aliases_norm = [normalize_entity_name(al) for al in note["aliases"]]
            if note_name_norm == alias_norm or alias_norm in note_aliases_norm:
                vault_claimers.append(note)

        if not vault_claimers:
            continue

        if len(vault_claimers) == 1:
            claimer = vault_claimers[0]
            if db_person_vault_id != claimer["id"]:
                mismatches.append(
                    {
                        "alias": alias_norm,
                        "db_person_id": db_person_id,
                        "db_person_name": db_person_display_name,
                        "db_person_vault_id": db_person_vault_id,
                        "vault_note": {
                            "id": claimer["id"],
                            "name": claimer["name"],
                            "path": str(claimer["file_path"]),
                        },
                    }
                )
        else:
            compound_conflicts.append(
                {
                    "alias": alias_norm,
                    "db_person_id": db_person_id,
                    "db_person_name": db_person_display_name,
                    "db_person_vault_id": db_person_vault_id,
                    "vault_claimers": [
                        {"id": c["id"], "name": c["name"], "path": str(c["file_path"])}
                        for c in vault_claimers
                    ],
                }
            )

    return {"mismatches": mismatches, "compound_conflicts": compound_conflicts}


def sync_people_in_tx(
    conn: sqlite3.Connection,
    people_notes_map: Dict[str, Any],
    property_report: Dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    skipped_relation_merges = []
    skipped_property_merges = []
    replaced_properties_count = 0
    replaced_values_count = 0
    deleted_properties_count = 0
    deleted_values_count = 0

    invalid_properties = (
        property_report.get("invalid_properties", []) if property_report else []
    )
    parsed_props_by_note = (
        property_report.get("parsed_properties_by_note_id", {})
        if property_report
        else {}
    )
    missing_props_by_note = (
        property_report.get("missing_properties_by_note_id", {})
        if property_report
        else {}
    )

    # 1. Group notes by note ID (since map is normalized_name -> PersonNote, multiple keys map to same dict)
    seen_note_ids = set()
    unique_notes = []
    for note in people_notes_map.values():
        if note["id"] not in seen_note_ids:
            seen_note_ids.add(note["id"])
            unique_notes.append(note)

    for note in unique_notes:
        vault_id = note["id"]
        vault_name = note["name"]
        normalized_vault_name = normalize_entity_name(vault_name)

        # Build set of all matching normalized names/aliases for this note
        aliases_set = {normalized_vault_name}
        for alias in note["aliases"]:
            norm_alias = normalize_entity_name(alias)
            if norm_alias:
                aliases_set.add(norm_alias)

        cursor = conn.cursor()

        # DB Confirmed Alias Conflict Check:
        # If any of the names/aliases in aliases_set conflicts with DB confirmed aliases pointing to another person,
        # remove it from aliases_set to maintain DB confirmed alignment and prevent candidate absorption/person merging.
        # If the conflict involves the note's primary name, skip the entire note.
        safe_aliases_set = set()
        skip_entire_note = False
        for a_norm in aliases_set:
            cursor.execute(
                "SELECT person_id FROM person_aliases WHERE normalized_name = ?",
                (a_norm,),
            )
            row = cursor.fetchone()
            if row is not None:
                db_pid = row[0]
                cursor.execute(
                    "SELECT vault_id FROM people WHERE person_id = ?", (db_pid,)
                )
                p_row = cursor.fetchone()
                db_vault_id = p_row[0] if p_row else None
                if db_vault_id != vault_id:
                    if a_norm == normalized_vault_name:
                        logger.warning(
                            "Primary name conflict for '%s' (points to %s in DB, Vault note has %s). Skipping entire note.",
                            a_norm,
                            db_pid,
                            vault_id,
                        )
                        skip_entire_note = True
                        break
                    else:
                        logger.info(
                            "Maintaining DB confirmed alias for '%s' (points to %s, Vault note has %s). Skipped in candidate/merge matching.",
                            a_norm,
                            db_pid,
                            vault_id,
                        )
                        continue
            safe_aliases_set.add(a_norm)

        if skip_entire_note:
            continue

        aliases_set = safe_aliases_set
        if not aliases_set:
            continue

        # Step A: Resolve target person_id in the 'people' table with vault_id
        cursor.execute("SELECT person_id FROM people WHERE vault_id = ?", (vault_id,))
        row = cursor.fetchone()

        needs_final_update = False
        final_update_args = ()
        final_update_sql = ""
        # Old duplicates skipped due to self-relation conflict keep their
        # people row (and normalized_name). Track them so the final rename
        # below can be skipped instead of violating UNIQUE(normalized_name).
        skipped_old_person_ids: set[str] = set()

        if row is not None:
            target_person_id = row[0]
            needs_final_update = True
            final_update_sql = "UPDATE people SET display_name = ?, normalized_name = ? WHERE person_id = ?"
            final_update_args = (vault_name, normalized_vault_name, target_person_id)
        else:
            # Check if there is an existing person with the same normalized name
            cursor.execute(
                "SELECT person_id FROM people WHERE normalized_name = ?",
                (normalized_vault_name,),
            )
            row = cursor.fetchone()
            if row is not None:
                target_person_id = row[0]
                needs_final_update = True
                final_update_sql = "UPDATE people SET vault_id = ?, display_name = ?, normalized_name = ? WHERE person_id = ?"
                final_update_args = (
                    vault_id,
                    vault_name,
                    normalized_vault_name,
                    target_person_id,
                )
            else:
                # Create a placeholder row with a guaranteed unique temp normalized_name
                target_person_id = f"peo_{uuid.uuid4().hex}"
                conn.execute(
                    "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES (?, ?, ?, ?)",
                    (
                        target_person_id,
                        f"temp_{target_person_id}",
                        vault_name,
                        vault_id,
                    ),
                )
                needs_final_update = True
                final_update_sql = (
                    "UPDATE people SET normalized_name = ? WHERE person_id = ?"
                )
                final_update_args = (normalized_vault_name, target_person_id)

        logger.info("Resolved person to person_id=%s", target_person_id)

        # Step B: Match and migrate unresolved candidates
        placeholders = ", ".join("?" for _ in aliases_set)
        cursor.execute(
            f"SELECT candidate_id, normalized_name FROM person_candidates WHERE status = 'unresolved' AND normalized_name IN ({placeholders})",
            list(aliases_set),
        )
        candidates = cursor.fetchall()

        for cand_row in candidates:
            cand_id = cand_row["candidate_id"]
            cand_norm = cand_row["normalized_name"]

            # Skip auto-absorption if this name/candidate has manual assignments
            cursor.execute(
                "SELECT COUNT(*) FROM summary_person_assignments WHERE normalized_name = ?",
                (cand_norm,),
            )
            if cursor.fetchone()[0] > 0:
                logger.info(
                    "Skipping candidate auto-absorption for '%s' because manual assignments exist",
                    cand_norm,
                )
                continue

            logger.info(
                "Migrating unresolved candidate (id=%s) to target person_id=%s",
                cand_id,
                target_person_id,
            )

            cursor.execute(
                "SELECT summary_id, note, display_order FROM summary_person_candidates WHERE candidate_id = ?",
                (cand_id,),
            )
            links = cursor.fetchall()

            for link in links:
                summary_id = link["summary_id"]
                cand_note = link["note"]
                cand_order = link["display_order"]

                cursor.execute(
                    "SELECT note, display_order FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, target_person_id),
                )
                existing_link = cursor.fetchone()

                if existing_link is not None:
                    notes_to_join = []
                    existing_note = existing_link["note"]
                    existing_order = existing_link["display_order"]

                    if existing_note and existing_note.strip():
                        notes_to_join.append(existing_note.strip())
                    if cand_note and cand_note.strip():
                        notes_to_join.append(cand_note.strip())

                    merged_note = "\n".join(notes_to_join) if notes_to_join else None
                    merged_order = merge_display_orders(existing_order, cand_order)

                    conn.execute(
                        "UPDATE summary_people SET note = ?, display_order = ? WHERE summary_id = ? AND person_id = ?",
                        (merged_note, merged_order, summary_id, target_person_id),
                    )
                    conn.execute(
                        "DELETE FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                        (summary_id, cand_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, target_person_id, cand_note, cand_order),
                    )
                    conn.execute(
                        "DELETE FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                        (summary_id, cand_id),
                    )

            conn.execute(
                "DELETE FROM person_candidates WHERE candidate_id = ?", (cand_id,)
            )

        # Step C: Match and migrate old duplicate 'people' records (vault_id IS NULL)
        cursor.execute(
            f"SELECT person_id, display_name FROM people WHERE vault_id IS NULL AND normalized_name IN ({placeholders})",
            list(aliases_set),
        )
        old_people = cursor.fetchall()

        for old_p_row in old_people:
            old_person_id = old_p_row["person_id"]
            old_display_name = old_p_row["display_name"]

            if old_person_id == target_person_id:
                continue

            # Check if migrating this person causes a self-relation
            rel_preview = preview_person_relation_merge(
                cursor, old_person_id, target_person_id
            )
            if rel_preview["self_relation_conflicts_count"] > 0:
                logger.warning(
                    "Skipping auto-merge of person '%s' (%s -> %s) due to self-relation conflict",
                    old_display_name,
                    old_person_id,
                    target_person_id,
                )
                skipped_items = [
                    {
                        "relation_id": imp["relation_id"],
                        "relation_type_slug": imp["relation_type_slug"],
                        "other_person_id": imp["other_person_id"],
                        "other_person_name": imp["other_person_name"],
                        "started_on": imp["started_on"],
                        "ended_on": imp["ended_on"],
                    }
                    for imp in rel_preview["relation_impacts"]
                    if imp["result_type"] == "self_relation_conflict"
                ]
                skipped_relation_merges.append(
                    {
                        "from_person_id": old_person_id,
                        "from_person_name": old_display_name,
                        "to_person_id": target_person_id,
                        "to_person_name": vault_name,
                        "reason": "統合により自己関係が発生するため自動統合をスキップしました。",
                        "skipped_relations": skipped_items,
                    }
                )
                skipped_old_person_ids.add(old_person_id)
                continue

            # Check if migrating this person causes a property conflict
            prop_preview = preview_person_property_merge(
                cursor, old_person_id, target_person_id
            )
            if prop_preview["property_conflicts_count"] > 0:
                logger.warning(
                    "Skipping auto-merge of person '%s' (%s -> %s) due to property conflict",
                    old_display_name,
                    old_person_id,
                    target_person_id,
                )
                for imp in prop_preview["property_impacts"]:
                    if imp["result_type"] == "property_conflict":
                        skipped_property_merges.append(
                            {
                                "from_person_id": old_person_id,
                                "from_person_name": old_display_name,
                                "to_person_id": target_person_id,
                                "to_person_name": vault_name,
                                "property_key": imp["property_key"],
                                "property_display_name": imp["property_display_name"],
                                "reason": imp["conflict_reason"]
                                or "自動統合で単数属性の期間重複が発生するため統合をスキップしました。",
                            }
                        )
                skipped_old_person_ids.add(old_person_id)
                continue

            logger.info(
                "Migrating old duplicate person (id=%s) to target person_id=%s",
                old_person_id,
                target_person_id,
            )

            # Transfer relations safely
            transfer_person_relations_on_merge(
                cursor, old_person_id, target_person_id
            )

            # Transfer properties safely
            transfer_person_properties_on_merge(
                cursor, old_person_id, target_person_id
            )

            cursor.execute(
                "SELECT summary_id, note, display_order FROM summary_people WHERE person_id = ?",
                (old_person_id,),
            )
            old_links = cursor.fetchall()

            for old_link in old_links:
                summary_id = old_link["summary_id"]
                old_note = old_link["note"]
                old_order = old_link["display_order"]

                cursor.execute(
                    "SELECT note, display_order FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, target_person_id),
                )
                existing_link = cursor.fetchone()

                if existing_link is not None:
                    notes_to_join = []
                    existing_note = existing_link["note"]
                    existing_order = existing_link["display_order"]

                    if existing_note and existing_note.strip():
                        notes_to_join.append(existing_note.strip())
                    if old_note and old_note.strip():
                        notes_to_join.append(old_note.strip())

                    merged_note = "\n".join(notes_to_join) if notes_to_join else None
                    merged_order = merge_display_orders(existing_order, old_order)

                    conn.execute(
                        "UPDATE summary_people SET note = ?, display_order = ? WHERE summary_id = ? AND person_id = ?",
                        (merged_note, merged_order, summary_id, target_person_id),
                    )
                    conn.execute(
                        "DELETE FROM summary_people WHERE summary_id = ? AND person_id = ?",
                        (summary_id, old_person_id),
                    )
                else:
                    conn.execute(
                        "UPDATE summary_people SET person_id = ? WHERE summary_id = ? AND person_id = ?",
                        (target_person_id, summary_id, old_person_id),
                    )

            conn.execute("DELETE FROM people WHERE person_id = ?", (old_person_id,))

        if needs_final_update and skipped_old_person_ids:
            # All Step-A branches rename the target to normalized_vault_name.
            # A skipped duplicate still holds its normalized_name row, so
            # applying the rename would violate UNIQUE(people.normalized_name)
            # and roll back the whole sync. Skip only the final rename here;
            # the skip record above and all completed merges stay intact.
            skip_placeholders = ", ".join("?" for _ in skipped_old_person_ids)
            cursor.execute(
                f"SELECT person_id FROM people WHERE normalized_name = ? AND person_id IN ({skip_placeholders})",
                (normalized_vault_name, *skipped_old_person_ids),
            )
            blocker = cursor.fetchone()
            if blocker is not None:
                logger.warning(
                    "Skipping final rename of person '%s' (%s) to normalized_name '%s' because skipped duplicate '%s' still holds that name (self-relation conflict)",
                    vault_name,
                    target_person_id,
                    normalized_vault_name,
                    blocker[0],
                )
                needs_final_update = False

        if needs_final_update:
            conn.execute(final_update_sql, final_update_args)

        # Apply Vault property projections for target_person_id
        parsed_props_by_def = parsed_props_by_note.get(vault_id, {})
        missing_prop_def_ids = missing_props_by_note.get(vault_id, [])

        now_iso = datetime.now(JST).isoformat()

        # 1. Replace valid parsed properties
        for def_id, item_list in parsed_props_by_def.items():
            cursor.execute(
                "DELETE FROM person_property_values WHERE person_id = ? AND property_definition_id = ? AND source_type = 'vault'",
                (target_person_id, def_id),
            )
            replaced_properties_count += 1
            cursor.execute(
                "SELECT cardinality FROM person_property_definitions WHERE property_definition_id = ?",
                (def_id,),
            )
            card_row = cursor.fetchone()
            if card_row is not None and card_row[0] == "single":
                effective_items = _consolidate_single_cardinality_items(item_list)
            else:
                effective_items = item_list
            replaced_values_count += len(effective_items)

            for item in effective_items:
                val_id = f"propval_{uuid.uuid4().hex}"
                cursor.execute(
                    """
                    INSERT INTO person_property_values (
                        property_value_id, person_id, property_definition_id, source_type,
                        value_text, value_date, value_number, value_boolean, option_id,
                        valid_from, valid_until, note, created_at, updated_at
                    ) VALUES (?, ?, ?, 'vault', ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        val_id,
                        target_person_id,
                        def_id,
                        item["value_text"],
                        item["value_date"],
                        item["value_number"],
                        item["value_boolean"],
                        item["option_id"],
                        item["valid_from"],
                        item["valid_until"],
                        now_iso,
                        now_iso,
                    ),
                )

        # 2. Delete missing vault properties
        for def_id in missing_prop_def_ids:
            cursor.execute(
                "SELECT COUNT(*) FROM person_property_values WHERE person_id = ? AND property_definition_id = ? AND source_type = 'vault'",
                (target_person_id, def_id),
            )
            ex_cnt = cursor.fetchone()[0]
            if ex_cnt > 0:
                cursor.execute(
                    "DELETE FROM person_property_values WHERE person_id = ? AND property_definition_id = ? AND source_type = 'vault'",
                    (target_person_id, def_id),
                )
                deleted_properties_count += 1
                deleted_values_count += ex_cnt

    property_sync_summary = {
        "replaced_properties_count": replaced_properties_count,
        "replaced_values_count": replaced_values_count,
        "deleted_properties_count": deleted_properties_count,
        "deleted_values_count": deleted_values_count,
        "invalid_properties": invalid_properties,
        "skipped_property_merges": skipped_property_merges,
    }

    return skipped_relation_merges, property_sync_summary


def log_vault_report_to_cli(
    report: dict[str, Any], db_conflicts: dict[str, Any]
) -> None:
    if report.get("file_deficiencies"):
        logger.warning("=== File Deficiencies (ファイル不備) ===")
        for fd in report["file_deficiencies"]:
            logger.warning(f"  - Path: {fd['path']}")
            logger.warning(f"    Message: {fd['message']}")

    if report.get("duplicate_ids"):
        logger.warning("=== Duplicate IDs (重複ID) ===")
        for d_id in report["duplicate_ids"]:
            logger.warning(f"  - ID: {d_id['id']}")
            logger.warning(f"    Paths: {', '.join(d_id['paths'])}")

    if report.get("normalized_name_collisions"):
        logger.warning("=== Normalized Name Collisions (正規名衝突) ===")
        for col in report["normalized_name_collisions"]:
            logger.warning(f"  - Normalized Name: {col['normalized_name']}")
            for n in col["notes"]:
                logger.warning(f"    * ID: {n['id']}, Path: {n['path']}")

    if report.get("alias_collisions"):
        logger.warning("=== Alias Collisions (alias衝突) ===")
        for col in report["alias_collisions"]:
            logger.warning(f"  - Alias: {col['alias']}")
            for n in col["notes"]:
                logger.warning(
                    f"    * ID: {n['id']}, Path: {n['path']}, Role: {n['role']}"
                )

    if db_conflicts.get("mismatches"):
        logger.warning(
            "=== DB Confirmed Alias vs Vault Mismatches (DB確定別名とVault入力の不一致) ==="
        )
        for m in db_conflicts["mismatches"]:
            logger.warning(f"  - Alias: {m['alias']}")
            logger.warning(
                f"    DB Person ID: {m['db_person_id']}, Name: {m['db_person_name']}"
            )
            logger.warning(
                f"    Vault Note ID: {m['vault_note']['id']}, Name: {m['vault_note']['name']}, Path: {m['vault_note']['path']}"
            )

    if db_conflicts.get("compound_conflicts"):
        logger.warning(
            "=== DB Confirmed Alias vs Vault Compound Conflicts (複合衝突) ==="
        )
        for cc in db_conflicts["compound_conflicts"]:
            logger.warning(f"  - Alias: {cc['alias']}")
            logger.warning(
                f"    DB Person ID: {cc['db_person_id']}, Name: {cc['db_person_name']}"
            )
            for vc in cc["vault_claimers"]:
                logger.warning(
                    f"    * Vault Note ID: {vc['id']}, Name: {vc['name']}, Path: {vc['path']}"
                )

    invalid_props = report.get("property_report", {}).get("invalid_properties", [])
    if invalid_props:
        logger.warning("=== Invalid Vault Properties (不正なVault属性) ===")
        for ip in invalid_props:
            logger.warning(f"  - Person: {ip['person_name']} ({ip['person_id']})")
            logger.warning(
                f"    Property: {ip['property_display_name']} ({ip['property_key']})"
            )
            logger.warning(f"    Reason: {ip['reason']}")


def main() -> None:
    logger.info("Starting sync of people from Vault notes...")
    conn = get_db_connection()
    try:
        people_notes_map, report = load_people_notes_with_report(conn)

        with conn:
            # 1. Detect DB conflicts
            db_conflicts = get_db_vault_conflicts_report(
                conn, report.get("parsed_notes", [])
            )

            # 2. Log report details to CLI
            log_vault_report_to_cli(report, db_conflicts)

            # 3. Synchronize safely
            skipped_relation_merges, prop_summary = sync_people_in_tx(
                conn, people_notes_map, report.get("property_report")
            )

            if skipped_relation_merges:
                logger.warning(
                    "=== Skipped Relation Merges (自己関係競合による自動統合スキップ) ==="
                )
                for srm in skipped_relation_merges:
                    logger.warning(
                        f"  - From: {srm['from_person_name']} ({srm['from_person_id']}) -> To: {srm['to_person_name']} ({srm['to_person_id']})"
                    )
                    logger.warning(f"    Reason: {srm['reason']}")
                    for rel in srm.get("skipped_relations", []):
                        logger.warning(
                            f"    Relation: {rel['relation_type_slug']} with {rel['other_person_name']} ({rel['other_person_id']})"
                        )

            if prop_summary.get("skipped_property_merges"):
                logger.warning(
                    "=== Skipped Property Merges (属性競合による自動統合スキップ) ==="
                )
                for spm in prop_summary["skipped_property_merges"]:
                    logger.warning(
                        f"  - From: {spm['from_person_name']} ({spm['from_person_id']}) -> To: {spm['to_person_name']} ({spm['to_person_id']})"
                    )
                    logger.warning(
                        f"    Property: {spm['property_display_name']} ({spm['property_key']})"
                    )
                    logger.warning(f"    Reason: {spm['reason']}")

            logger.info(
                "Property sync completed: Replaced %d properties (%d values), Deleted %d missing properties (%d values).",
                prop_summary["replaced_properties_count"],
                prop_summary["replaced_values_count"],
                prop_summary["deleted_properties_count"],
                prop_summary["deleted_values_count"],
            )

        logger.info("People sync completed successfully.")
    except Exception:
        logger.exception("Failed to sync people from Vault notes")
        raise
    finally:
        conn.close()
