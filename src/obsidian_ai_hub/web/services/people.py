from typing import Any, Optional

from obsidian_ai_hub.database import get_db_connection


# --- Custom Exception classes for Conflict checks ---


class AliasConflictError(ValueError):
    def __init__(self, existing_person_id: str, existing_person_name: str):
        super().__init__("Conflict: This alias is already confirmed for another person")
        self.existing_person_id = existing_person_id
        self.existing_person_name = existing_person_name


class MainNameConflictError(ValueError):
    def __init__(self, existing_person_id: str, existing_person_name: str):
        super().__init__("Conflict: This name matches another person's normalized name")
        self.existing_person_id = existing_person_id
        self.existing_person_name = existing_person_name


class AssignmentConflictError(ValueError):
    def __init__(
        self,
        message="Conflict: Cannot resolve globally because manual assignments exist for this normalized name",
    ):
        super().__init__(message)


class VaultLinkedPersonError(ValueError):
    def __init__(self, message="Conflict: Vault-linked people cannot be edited."):
        super().__init__(message)


# --- People Management services ---


def list_people() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.person_id, p.display_name, p.normalized_name, p.vault_id, COUNT(sp.summary_id) AS summary_count
            FROM people p
            LEFT JOIN summary_people sp ON p.person_id = sp.person_id
            GROUP BY p.person_id, p.display_name, p.normalized_name, p.vault_id
            ORDER BY summary_count DESC, p.display_name ASC, p.person_id ASC
        """)
        people_rows = [dict(r) for r in cursor.fetchall()]

        for p in people_rows:
            cursor.execute(
                "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
                (p["person_id"],),
            )
            p["aliases"] = [dict(r) for r in cursor.fetchall()]
        return people_rows
    finally:
        conn.close()


def get_person_detail(person_id: str) -> Optional[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
            (person_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        p = dict(row)

        cursor.execute(
            "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
            (p["person_id"],),
        )
        p["aliases"] = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            """
            SELECT s.summary_id, s.period_type, s.period_key, sp.note, sp.display_order
            FROM summary_people sp
            JOIN summaries s ON sp.summary_id = s.summary_id
            WHERE sp.person_id = ?
            ORDER BY s.period_start DESC, s.period_key DESC
            """,
            (person_id,),
        )
        p["summaries"] = [dict(r) for r in cursor.fetchall()]

        # Compute counts
        cursor.execute(
            "SELECT COUNT(*) FROM summary_people WHERE person_id = ?", (person_id,)
        )
        summaries_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM person_aliases WHERE person_id = ?", (person_id,)
        )
        aliases_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM summary_person_assignments WHERE person_id = ?",
            (person_id,),
        )
        assignments_count = cursor.fetchone()[0]

        p["summary_count"] = summaries_count
        p["relation_counts"] = {
            "summaries": summaries_count,
            "aliases": aliases_count,
            "assignments": assignments_count,
        }

        return p
    finally:
        conn.close()


def update_unlinked_person(
    person_id: str,
    display_name: Optional[str] = None,
    aliases: Optional[list[str]] = None,
) -> dict:
    from obsidian_ai_hub.summary.store import normalize_entity_name

    if display_name is None and aliases is None:
        raise ValueError(
            "At least display_name or aliases must be specified for update."
        )

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # 1. Fetch current person row
            cursor.execute(
                "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
                (person_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise FileNotFoundError("Person not found")
            person = dict(row)

            # Reject if Vault-linked
            if person.get("vault_id") is not None:
                raise VaultLinkedPersonError()

            # Load current aliases for self-conflict exclusion
            cursor.execute(
                "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
                (person_id,),
            )
            current_aliases = [dict(r) for r in cursor.fetchall()]
            current_names = {person["normalized_name"]} | {
                a["normalized_name"] for a in current_aliases
            }

            # 2. Determine target main name and aliases
            target_display_name = person["display_name"]
            target_normalized_name = person["normalized_name"]

            if display_name is not None:
                stripped_display_name = display_name.strip()
                if not stripped_display_name:
                    raise ValueError("表示名に空文字を指定することはできません。")
                target_display_name = stripped_display_name
                target_normalized_name = normalize_entity_name(stripped_display_name)

            target_aliases = []
            if aliases is not None:
                seen_norm_aliases = set()
                for alias in aliases:
                    stripped_alias = alias.strip()
                    if not stripped_alias:
                        raise ValueError("別名に空文字を指定することはできません。")
                    norm_alias = normalize_entity_name(stripped_alias)
                    if norm_alias in seen_norm_aliases:
                        raise ValueError("重複した別名を指定することはできません。")
                    seen_norm_aliases.add(norm_alias)
                    target_aliases.append(
                        {"normalized_name": norm_alias, "display_name": stripped_alias}
                    )
            else:
                # Keep current aliases
                target_aliases = current_aliases

            # 3. Conflict checks
            names_to_check = [target_normalized_name] + [
                a["normalized_name"] for a in target_aliases
            ]

            for name_to_check in names_to_check:
                # Conflict with another person's main name
                cursor.execute(
                    "SELECT person_id, display_name FROM people WHERE normalized_name = ? AND person_id != ?",
                    (name_to_check, person_id),
                )
                other_main = cursor.fetchone()
                if other_main is not None:
                    raise MainNameConflictError(
                        other_main["person_id"], other_main["display_name"]
                    )

                # Conflict with another person's alias
                cursor.execute(
                    "SELECT person_id, display_name FROM person_aliases WHERE normalized_name = ? AND person_id != ?",
                    (name_to_check, person_id),
                )
                other_alias = cursor.fetchone()
                if other_alias is not None:
                    raise AliasConflictError(
                        other_alias["person_id"], other_alias["display_name"]
                    )

                # Conflict with manual assignments (only newly specified)
                if name_to_check not in current_names:
                    cursor.execute(
                        "SELECT COUNT(*) FROM summary_person_assignments WHERE normalized_name = ?",
                        (name_to_check,),
                    )
                    if cursor.fetchone()[0] > 0:
                        raise AssignmentConflictError()

            # 4. Apply changes
            conn.execute(
                "UPDATE people SET display_name = ?, normalized_name = ? WHERE person_id = ?",
                (target_display_name, target_normalized_name, person_id),
            )

            if aliases is not None:
                conn.execute(
                    "DELETE FROM person_aliases WHERE person_id = ?", (person_id,)
                )
                for ta in target_aliases:
                    conn.execute(
                        "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
                        (ta["normalized_name"], person_id, ta["display_name"]),
                    )

        # On success, return updated person detail
        return get_person_detail(person_id)
    finally:
        conn.close()


def delete_person(person_id: str) -> dict:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT person_id FROM people WHERE person_id = ?", (person_id,)
            )
            if cursor.fetchone() is None:
                raise FileNotFoundError("Person not found")

            cursor.execute(
                "DELETE FROM summary_people WHERE person_id = ?", (person_id,)
            )
            deleted_summary_people = cursor.rowcount

            cursor.execute(
                "DELETE FROM person_aliases WHERE person_id = ?", (person_id,)
            )
            deleted_aliases = cursor.rowcount

            cursor.execute(
                "DELETE FROM summary_person_assignments WHERE person_id = ?",
                (person_id,),
            )
            deleted_assignments = cursor.rowcount

            cursor.execute("DELETE FROM people WHERE person_id = ?", (person_id,))

            return {
                "success": True,
                "deleted_summary_people": deleted_summary_people,
                "deleted_aliases": deleted_aliases,
                "deleted_assignments": deleted_assignments,
            }
    finally:
        conn.close()


def delete_person_alias(person_id: str, normalized_name: str) -> dict:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT person_id FROM people WHERE person_id = ?", (person_id,)
            )
            if cursor.fetchone() is None:
                raise FileNotFoundError("Person not found")

            cursor.execute(
                "SELECT normalized_name, display_name FROM person_aliases WHERE normalized_name = ? AND person_id = ?",
                (normalized_name, person_id),
            )
            alias_row = cursor.fetchone()
            if alias_row is None:
                raise FileNotFoundError("Alias not found for this person")

            conn.execute(
                "DELETE FROM person_aliases WHERE normalized_name = ? AND person_id = ?",
                (normalized_name, person_id),
            )

        return get_person_detail(person_id)
    finally:
        conn.close()
