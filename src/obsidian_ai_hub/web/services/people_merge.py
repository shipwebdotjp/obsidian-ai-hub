import sqlite3
from typing import Any, Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.people_sync.sync import merge_display_orders
from obsidian_ai_hub.utils.people_loader import load_people_notes_with_report


def get_duplicate_candidates() -> dict[str, Any]:
    safe_map, report = load_people_notes_with_report()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Group 1: Unlinked people matching safe Vault input
        cursor.execute(
            "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE vault_id IS NULL"
        )
        unlinked_people = [dict(r) for r in cursor.fetchall()]

        vault_matches = []
        for p in unlinked_people:
            norm = p["normalized_name"]
            if norm in safe_map:
                v_note = safe_map[norm]
                vault_matches.append(
                    {
                        "unlinked_person": p,
                        "vault_person": {
                            "id": v_note["id"],
                            "name": v_note["name"],
                            "path": str(v_note["file_path"]),
                        },
                    }
                )

        # Group 2: Same non-NULL vault_id across multiple people records
        cursor.execute(
            """
            SELECT vault_id, count(*) as cnt
            FROM people
            WHERE vault_id IS NOT NULL
            GROUP BY vault_id
            HAVING cnt > 1
            """
        )
        duplicate_vault_ids = [r["vault_id"] for r in cursor.fetchall()]

        same_vault_id_groups = []
        for v_id in duplicate_vault_ids:
            cursor.execute(
                "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE vault_id = ?",
                (v_id,),
            )
            members = [dict(r) for r in cursor.fetchall()]
            same_vault_id_groups.append({"vault_id": v_id, "people": members})

        return {
            "vault_matches": vault_matches,
            "same_vault_id_groups": same_vault_id_groups,
        }
    finally:
        conn.close()


def consolidate_summary_links(
    from_note: Optional[str],
    to_note: Optional[str],
    from_order: Optional[int],
    to_order: Optional[int],
) -> tuple[Optional[str], Optional[int]]:
    notes_to_join = []
    if to_note and to_note.strip():
        notes_to_join.append(to_note.strip())
    if from_note and from_note.strip():
        notes_to_join.append(from_note.strip())
    merged_note = "\n".join(notes_to_join) if notes_to_join else None
    merged_order = merge_display_orders(to_order, from_order)
    return merged_note, merged_order


def verify_people_merge(
    cursor: sqlite3.Cursor, from_person_id: str, to_person_id: str
) -> dict:
    if from_person_id == to_person_id:
        return {
            "allowed": False,
            "reason": "統合元と統合主に同じ人物が指定されています。",
            "transferred_summaries_count": 0,
            "transferred_aliases_count": 0,
            "alias_transfers": [],
            "merged_summaries": [],
        }

    # 1. Fetch people
    cursor.execute(
        "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
        (from_person_id,),
    )
    from_row = cursor.fetchone()
    if from_row is None:
        return {
            "allowed": False,
            "reason": "統合元の人物が見つかりません。",
            "transferred_summaries_count": 0,
            "transferred_aliases_count": 0,
            "alias_transfers": [],
            "merged_summaries": [],
        }
    from_p = dict(from_row)

    cursor.execute(
        "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
        (to_person_id,),
    )
    to_row = cursor.fetchone()
    if to_row is None:
        return {
            "allowed": False,
            "reason": "統合先の人物が見つかりません。",
            "from_person": from_p,
            "transferred_summaries_count": 0,
            "transferred_aliases_count": 0,
            "alias_transfers": [],
            "merged_summaries": [],
        }
    to_p = dict(to_row)

    # 2. Get aliases
    cursor.execute(
        "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
        (from_person_id,),
    )
    from_aliases = [dict(r) for r in cursor.fetchall()]
    from_p["aliases"] = from_aliases

    cursor.execute(
        "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
        (to_person_id,),
    )
    to_aliases = [dict(r) for r in cursor.fetchall()]
    to_p["aliases"] = to_aliases

    # 3. Vault ID verification
    from_vault = from_p.get("vault_id")
    to_vault = to_p.get("vault_id")

    # Reject Vault-linked to Unlinked
    if from_vault is not None and to_vault is None:
        return {
            "allowed": False,
            "reason": "Vault連携済み人物を未連携人物へ寄せる操作は拒否されます。",
            "from_person": from_p,
            "to_person": to_p,
            "transferred_summaries_count": 0,
            "transferred_aliases_count": 0,
            "alias_transfers": [],
            "merged_summaries": [],
        }

    # Reject different vault_id values
    if from_vault is not None and to_vault is not None and from_vault != to_vault:
        return {
            "allowed": False,
            "reason": "異なるVault IDを持つ人物同士の統合は拒否されます。",
            "from_person": from_p,
            "to_person": to_p,
            "transferred_summaries_count": 0,
            "transferred_aliases_count": 0,
            "alias_transfers": [],
            "merged_summaries": [],
        }

    # 4. Third-party conflict check
    # Gather the set of normalized names that would be transferred
    source_names = {from_p["normalized_name"]} | {
        a["normalized_name"] for a in from_aliases
    }

    if source_names:
        placeholders = ", ".join("?" for _ in source_names)

        # Check conflicts with third-party main name
        cursor.execute(
            f"SELECT person_id, display_name, normalized_name FROM people WHERE normalized_name IN ({placeholders}) AND person_id NOT IN (?, ?)",
            list(source_names) + [from_person_id, to_person_id],
        )
        conflicting_people = cursor.fetchall()
        if conflicting_people:
            names_str = ", ".join(r["display_name"] for r in conflicting_people)
            return {
                "allowed": False,
                "reason": f"統合元の名前または別名が、第三者の正規名と衝突しています（衝突対象: {names_str}）。",
                "from_person": from_p,
                "to_person": to_p,
                "transferred_summaries_count": 0,
                "transferred_aliases_count": 0,
                "alias_transfers": [],
                "merged_summaries": [],
            }

        # Check conflicts with third-party aliases
        cursor.execute(
            f"SELECT person_id, display_name, normalized_name FROM person_aliases WHERE normalized_name IN ({placeholders}) AND person_id NOT IN (?, ?)",
            list(source_names) + [from_person_id, to_person_id],
        )
        conflicting_aliases = cursor.fetchall()
        if conflicting_aliases:
            names_str = ", ".join(r["display_name"] for r in conflicting_aliases)
            return {
                "allowed": False,
                "reason": f"統合元の名前または別名が、第三者の別名と衝突しています（衝突対象: {names_str}）。",
                "from_person": from_p,
                "to_person": to_p,
                "transferred_summaries_count": 0,
                "transferred_aliases_count": 0,
                "alias_transfers": [],
                "merged_summaries": [],
            }

    # 5. Build Alias Transfers Preview
    alias_transfers = []
    seen_normalized = {a["normalized_name"] for a in to_aliases} | {
        to_p["normalized_name"]
    }

    for fa in from_aliases:
        norm = fa["normalized_name"]
        if norm not in seen_normalized:
            alias_transfers.append(
                {"normalized_name": norm, "display_name": fa["display_name"]}
            )
            seen_normalized.add(norm)

    from_p_norm = from_p["normalized_name"]
    if from_p_norm not in seen_normalized:
        alias_transfers.append(
            {"normalized_name": from_p_norm, "display_name": from_p["display_name"]}
        )

    # 6. Build Merged Summaries Preview
    cursor.execute(
        "SELECT summary_id, note, display_order FROM summary_people WHERE person_id = ?",
        (from_person_id,),
    )
    from_links = {r["summary_id"]: dict(r) for r in cursor.fetchall()}

    cursor.execute(
        "SELECT summary_id, note, display_order FROM summary_people WHERE person_id = ?",
        (to_person_id,),
    )
    to_links = {r["summary_id"]: dict(r) for r in cursor.fetchall()}

    merged_summaries = []
    for summary_id, from_link in from_links.items():
        if summary_id in to_links:
            to_link = to_links[summary_id]

            # Fetch summary details
            cursor.execute(
                "SELECT period_key, period_type FROM summaries WHERE summary_id = ?",
                (summary_id,),
            )
            sum_row = cursor.fetchone()
            if sum_row:
                period_key = sum_row["period_key"]
                period_type = sum_row["period_type"]
            else:
                period_key = "unknown"
                period_type = "unknown"

            from_note = from_link["note"]
            to_note = to_link["note"]

            merged_note, merged_display_order = consolidate_summary_links(
                from_note, to_note, from_link["display_order"], to_link["display_order"]
            )

            merged_summaries.append(
                {
                    "summary_id": summary_id,
                    "period_key": period_key,
                    "period_type": period_type,
                    "from_note": from_note,
                    "to_note": to_note,
                    "merged_note": merged_note,
                    "merged_display_order": merged_display_order,
                }
            )

    return {
        "allowed": True,
        "reason": "統合可能です。",
        "from_person": from_p,
        "to_person": to_p,
        "transferred_summaries_count": len(from_links),
        "transferred_aliases_count": len(alias_transfers),
        "alias_transfers": alias_transfers,
        "merged_summaries": merged_summaries,
    }


def preview_people_merge(from_person_id: str, to_person_id: str) -> dict:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        return verify_people_merge(cursor, from_person_id, to_person_id)
    finally:
        conn.close()


def merge_people(from_person_id: str, to_person_id: str) -> bool:
    if from_person_id == to_person_id:
        raise ValueError("Source and target person IDs for merge cannot be identical.")

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # Verify before merge
            preview = verify_people_merge(cursor, from_person_id, to_person_id)
            if not preview["allowed"]:
                raise ValueError(preview["reason"])

            from_p = preview["from_person"]

            # 2. Migrate summary links
            cursor.execute(
                "SELECT summary_id, note, display_order FROM summary_people WHERE person_id = ?",
                (from_person_id,),
            )
            links = cursor.fetchall()

            for link in links:
                summary_id = link["summary_id"]
                note = link["note"]
                order = link["display_order"]

                cursor.execute(
                    "SELECT note, display_order FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, to_person_id),
                )
                existing_link = cursor.fetchone()

                if existing_link is not None:
                    merged_note, merged_order = consolidate_summary_links(
                        note,
                        existing_link["note"],
                        order,
                        existing_link["display_order"],
                    )

                    conn.execute(
                        "UPDATE summary_people SET note = ?, display_order = ? WHERE summary_id = ? AND person_id = ?",
                        (merged_note, merged_order, summary_id, to_person_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, to_person_id, note, order),
                    )

                conn.execute(
                    "DELETE FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, from_person_id),
                )

            # 3. Migrate aliases
            # Migrate only the ones in preview["alias_transfers"], without OR IGNORE, allowing it to fail on unexpected conflict
            from_p_norm = from_p["normalized_name"]
            for al in preview["alias_transfers"]:
                norm = al["normalized_name"]
                disp = al["display_name"]
                if norm == from_p_norm:
                    conn.execute(
                        "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
                        (norm, to_person_id, disp),
                    )
                else:
                    conn.execute(
                        "UPDATE person_aliases SET person_id = ? WHERE normalized_name = ?",
                        (to_person_id, norm),
                    )

            # Delete any remaining aliases under from_person_id
            conn.execute(
                "DELETE FROM person_aliases WHERE person_id = ?", (from_person_id,)
            )

            # 3b. Update summary_person_assignments for from_person_id to to_person_id
            conn.execute(
                "UPDATE OR REPLACE summary_person_assignments SET person_id = ? WHERE person_id = ?",
                (to_person_id, from_person_id),
            )

            # 4. Delete source person
            conn.execute("DELETE FROM people WHERE person_id = ?", (from_person_id,))

            return True
    finally:
        conn.close()
