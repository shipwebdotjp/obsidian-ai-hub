from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any, Dict

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils.people_loader import load_people_notes_with_report
from obsidian_ai_hub.summary.store import normalize_entity_name

logger = logging.getLogger(__name__)


def merge_display_orders(order1: int | None, order2: int | None) -> int | None:
    if order1 is None and order2 is None:
        return None
    if order1 is None:
        return order2
    if order2 is None:
        return order1
    return min(order1, order2)


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
    conn: sqlite3.Connection, people_notes_map: Dict[str, Any]
) -> None:
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
            f"SELECT person_id FROM people WHERE vault_id IS NULL AND normalized_name IN ({placeholders})",
            list(aliases_set),
        )
        old_people = cursor.fetchall()

        for old_p_row in old_people:
            old_person_id = old_p_row["person_id"]

            if old_person_id == target_person_id:
                continue

            logger.info(
                "Migrating old duplicate person (id=%s) to target person_id=%s",
                old_person_id,
                target_person_id,
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

        if needs_final_update:
            conn.execute(final_update_sql, final_update_args)


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


def main() -> None:
    logger.info("Starting sync of people from Vault notes...")
    people_notes_map, report = load_people_notes_with_report()

    conn = get_db_connection()
    try:
        with conn:
            # 1. Detect DB conflicts
            db_conflicts = get_db_vault_conflicts_report(
                conn, report.get("parsed_notes", [])
            )

            # 2. Log report details to CLI
            log_vault_report_to_cli(report, db_conflicts)

            # 3. Synchronize safely
            sync_people_in_tx(conn, people_notes_map)
        logger.info("People sync completed successfully.")
    except Exception:
        logger.exception("Failed to sync people from Vault notes")
        raise
    finally:
        conn.close()
