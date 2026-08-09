import uuid
from typing import Any, Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.people_sync.sync import merge_display_orders
from obsidian_ai_hub.web.services.people import (
    AliasConflictError,
    AssignmentConflictError,
    MainNameConflictError,
    get_person_detail,
)


class CandidateRejectedError(ValueError):
    def __init__(self, message="却下済み候補を操作するには、先に再開してください。"):
        super().__init__(message)


def list_person_candidates(status: str = "unresolved") -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT candidate_id, display_name, normalized_name, status FROM person_candidates WHERE status = ?",
            (status,)
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def reject_person_candidate(candidate_id: str) -> bool:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT candidate_id FROM person_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            if cursor.fetchone() is None:
                raise FileNotFoundError("Candidate not found")
            conn.execute(
                "UPDATE person_candidates SET status = 'rejected' WHERE candidate_id = ?",
                (candidate_id,),
            )
            return True
    finally:
        conn.close()


def reopen_person_candidate(candidate_id: str) -> bool:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT candidate_id FROM person_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            if cursor.fetchone() is None:
                raise FileNotFoundError("Candidate not found")
            conn.execute(
                "UPDATE person_candidates SET status = 'unresolved' WHERE candidate_id = ?",
                (candidate_id,),
            )
            return True
    finally:
        conn.close()


def get_person_candidate_detail(candidate_id: str) -> Optional[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT candidate_id, display_name, normalized_name, status FROM person_candidates WHERE candidate_id = ?",
            (candidate_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        c = dict(row)

        cursor.execute(
            """
            SELECT s.summary_id, s.period_type, s.period_key, spc.note, spc.display_order
            FROM summary_person_candidates spc
            JOIN summaries s ON spc.summary_id = s.summary_id
            WHERE spc.candidate_id = ?
            ORDER BY s.period_start DESC, s.period_key DESC
            """,
            (candidate_id,),
        )
        c["summaries"] = [dict(r) for r in cursor.fetchall()]

        # Get assigned summaries count
        cursor.execute(
            "SELECT COUNT(*) FROM summary_person_assignments WHERE normalized_name = ?",
            (c["normalized_name"],),
        )
        c["assigned_summaries_count"] = cursor.fetchone()[0]

        return c
    finally:
        conn.close()


def assign_candidate_summary(
    candidate_id: str, summary_id: str, target_person_id: str
) -> bool:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # 1. Fetch candidate to identify normalized_name
            cursor.execute(
                "SELECT candidate_id, display_name, normalized_name, status FROM person_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            cand_row = cursor.fetchone()
            if cand_row is None:
                raise FileNotFoundError("Candidate not found")
            cand = dict(cand_row)
            if cand["status"] == "rejected":
                raise CandidateRejectedError()
            normalized_name = cand["normalized_name"]

            # 2. Check if candidate-summary link exists
            cursor.execute(
                "SELECT note, display_order FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                (summary_id, candidate_id),
            )
            link_row = cursor.fetchone()
            if link_row is None:
                raise FileNotFoundError("Candidate summary link not found")
            cand_note = link_row["note"]
            cand_order = link_row["display_order"]

            # 3. Check target person existence and vault-linked constraint
            cursor.execute(
                "SELECT person_id, display_name, vault_id FROM people WHERE person_id = ?",
                (target_person_id,),
            )
            target_row = cursor.fetchone()
            if target_row is None:
                raise ValueError("Target person not found")
            target = dict(target_row)
            if not target.get("vault_id"):
                raise ValueError("割当先はVault連携済み人物のみに限定されています。")

            # 4. Remove candidate's link from summary_person_candidates
            conn.execute(
                "DELETE FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                (summary_id, candidate_id),
            )

            # 5. Insert/Save manual assignment to summary_person_assignments
            conn.execute(
                """
                INSERT OR REPLACE INTO summary_person_assignments (summary_id, normalized_name, person_id)
                VALUES (?, ?, ?)
                """,
                (summary_id, normalized_name, target_person_id),
            )

            # 6. Insert or merge/concatenate notes and display order in summary_people
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
            else:
                conn.execute(
                    "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                    (summary_id, target_person_id, cand_note, cand_order),
                )

            # 7. Delete the candidate if no remaining links exist
            cursor.execute(
                "SELECT COUNT(*) FROM summary_person_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            remaining_links_count = cursor.fetchone()[0]
            if remaining_links_count == 0:
                conn.execute(
                    "DELETE FROM person_candidates WHERE candidate_id = ?",
                    (candidate_id,),
                )

            return True
    finally:
        conn.close()


def resolve_person_candidate(
    candidate_id: str, target_person_id: str
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # 1. Fetch candidate
            cursor.execute(
                "SELECT candidate_id, display_name, normalized_name, status FROM person_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            cand_row = cursor.fetchone()
            if cand_row is None:
                raise ValueError("Candidate not found")
            cand = dict(cand_row)
            if cand["status"] == "rejected":
                raise CandidateRejectedError()

            # 1b. Check if there are any manual assignments for this candidate's normalized_name
            cursor.execute(
                "SELECT COUNT(*) FROM summary_person_assignments WHERE normalized_name = ?",
                (cand["normalized_name"],),
            )
            assigned_count = cursor.fetchone()[0]
            if assigned_count > 0:
                raise AssignmentConflictError()

            # 2. Fetch target person
            cursor.execute(
                "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
                (target_person_id,),
            )
            target_row = cursor.fetchone()
            if target_row is None:
                raise ValueError("Target person not found")
            target = dict(target_row)

            # Enforce target must be a Vault-linked person
            if not target.get("vault_id"):
                raise ValueError(
                    "未連携人物への解決は許可されていません。解決先はVault連携済みの人物だけに制限されています。"
                )

            normalized_name = cand["normalized_name"]

            # 3. Conflict check 1: person_aliases
            cursor.execute(
                "SELECT person_id, display_name FROM person_aliases WHERE normalized_name = ?",
                (normalized_name,),
            )
            alias_row = cursor.fetchone()
            if alias_row is not None and alias_row["person_id"] != target_person_id:
                raise AliasConflictError(
                    alias_row["person_id"], alias_row["display_name"]
                )

            # 4. Conflict check 2: people.normalized_name
            cursor.execute(
                "SELECT person_id, display_name FROM people WHERE normalized_name = ?",
                (normalized_name,),
            )
            main_name_row = cursor.fetchone()
            if (
                main_name_row is not None
                and main_name_row["person_id"] != target_person_id
            ):
                raise MainNameConflictError(
                    main_name_row["person_id"], main_name_row["display_name"]
                )

            # 5. Insert alias (Ensure we do a normal INSERT only if alias_row is None and raise error on fail)
            if alias_row is None:
                conn.execute(
                    "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
                    (normalized_name, target_person_id, cand["display_name"]),
                )

            # 6. Migrate summaries
            cursor.execute(
                "SELECT summary_id, note, display_order FROM summary_person_candidates WHERE candidate_id = ?",
                (candidate_id,),
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
                else:
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, target_person_id, cand_note, cand_order),
                    )

                conn.execute(
                    "DELETE FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                    (summary_id, candidate_id),
                )

            # 7. Delete candidate
            conn.execute(
                "DELETE FROM person_candidates WHERE candidate_id = ?", (candidate_id,)
            )

            return {"success": True}
    finally:
        conn.close()


def promote_person_candidate(
    candidate_id: str, display_name: str
) -> dict[str, Any]:
    from obsidian_ai_hub.summary.store import normalize_entity_name

    stripped_display_name = display_name.strip()
    if not stripped_display_name:
        raise ValueError("表示名に空文字を指定することはできません。")

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # 1. Fetch candidate
            cursor.execute(
                "SELECT candidate_id, display_name, normalized_name, status FROM person_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            cand_row = cursor.fetchone()
            if cand_row is None:
                raise FileNotFoundError("Candidate not found")
            cand = dict(cand_row)
            if cand["status"] == "rejected":
                raise CandidateRejectedError()

            # 2. Check if there are any manual assignments for this candidate's normalized_name
            cursor.execute(
                "SELECT COUNT(*) FROM summary_person_assignments WHERE normalized_name = ?",
                (cand["normalized_name"],),
            )
            if cursor.fetchone()[0] > 0:
                raise AssignmentConflictError()

            # 3. Conflict checks for the new display_name
            target_normalized = normalize_entity_name(stripped_display_name)

            # Conflict with another person's main name
            cursor.execute(
                "SELECT person_id, display_name FROM people WHERE normalized_name = ?",
                (target_normalized,),
            )
            main_row = cursor.fetchone()
            if main_row is not None:
                raise MainNameConflictError(main_row["person_id"], main_row["display_name"])

            # Conflict with another person's alias
            cursor.execute(
                "SELECT person_id, display_name FROM person_aliases WHERE normalized_name = ?",
                (target_normalized,),
            )
            alias_row = cursor.fetchone()
            if alias_row is not None:
                raise AliasConflictError(alias_row["person_id"], alias_row["display_name"])

            # 4. Create new unlinked person
            person_id = f"peo_{uuid.uuid4().hex}"
            conn.execute(
                "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES (?, ?, ?, NULL)",
                (person_id, target_normalized, stripped_display_name),
            )

            # 5. Save alias if candidate display_name differs from input display_name
            if target_normalized != cand["normalized_name"]:
                cursor.execute(
                    "SELECT person_id, display_name FROM people WHERE normalized_name = ?",
                    (cand["normalized_name"],),
                )
                alias_main_row = cursor.fetchone()
                if alias_main_row is not None:
                    raise MainNameConflictError(alias_main_row["person_id"], alias_main_row["display_name"])
                cursor.execute(
                    "SELECT person_id, display_name FROM person_aliases WHERE normalized_name = ?",
                    (cand["normalized_name"],),
                )
                alias_alias_row = cursor.fetchone()
                if alias_alias_row is not None:
                    raise AliasConflictError(alias_alias_row["person_id"], alias_alias_row["display_name"])
                conn.execute(
                    "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
                    (cand["normalized_name"], person_id, cand["display_name"]),
                )

            # 6. Migrate summaries from summary_person_candidates to summary_people
            cursor.execute(
                "SELECT summary_id, note, display_order FROM summary_person_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            links = cursor.fetchall()

            for link in links:
                summary_id = link["summary_id"]
                cand_note = link["note"]
                cand_order = link["display_order"]

                cursor.execute(
                    "SELECT note, display_order FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, person_id),
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
                        (merged_note, merged_order, summary_id, person_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, person_id, cand_note, cand_order),
                    )

                conn.execute(
                    "DELETE FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                    (summary_id, candidate_id),
                )

            # 7. Delete candidate
            conn.execute(
                "DELETE FROM person_candidates WHERE candidate_id = ?", (candidate_id,)
            )

        return get_person_detail(person_id)
    finally:
        conn.close()
