from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any, Dict

from obsidian_ai_hub import memory
from obsidian_ai_hub.utils.people_loader import load_and_validate_people_notes
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


def sync_people_in_tx(conn: sqlite3.Connection, people_notes_map: Dict[str, Any]) -> None:
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

        # Step A: Resolve target person_id in the 'people' table with vault_id
        cursor.execute("SELECT person_id FROM people WHERE vault_id = ?", (vault_id,))
        row = cursor.fetchone()

        needs_final_update = False
        final_update_args = ()
        final_update_sql = ""

        if row is not None:
            target_person_id = row[0]
            # Defer name and normalized_name update to avoid UNIQUE constraint conflicts
            needs_final_update = True
            final_update_sql = "UPDATE people SET display_name = ?, normalized_name = ? WHERE person_id = ?"
            final_update_args = (vault_name, normalized_vault_name, target_person_id)
        else:
            # Check if there is an existing person with the same normalized name
            cursor.execute("SELECT person_id FROM people WHERE normalized_name = ?", (normalized_vault_name,))
            row = cursor.fetchone()
            if row is not None:
                target_person_id = row[0]
                # Defer update of vault_id, display_name and normalized_name to avoid conflicts
                needs_final_update = True
                final_update_sql = "UPDATE people SET vault_id = ?, display_name = ?, normalized_name = ? WHERE person_id = ?"
                final_update_args = (vault_id, vault_name, normalized_vault_name, target_person_id)
            else:
                # Create a placeholder row with a guaranteed unique temp normalized_name
                # to satisfy foreign keys before matching/deleting duplicates
                target_person_id = f"peo_{uuid.uuid4().hex}"
                conn.execute(
                    "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES (?, ?, ?, ?)",
                    (target_person_id, f"temp_{target_person_id}", vault_name, vault_id),
                )
                needs_final_update = True
                final_update_sql = "UPDATE people SET normalized_name = ? WHERE person_id = ?"
                final_update_args = (normalized_vault_name, target_person_id)

        logger.info("Resolved person to person_id=%s", target_person_id)

        # Step B: Match and migrate unresolved candidates
        # Find candidates matching any of aliases_set
        placeholders = ", ".join("?" for _ in aliases_set)
        cursor.execute(
            f"SELECT candidate_id FROM person_candidates WHERE normalized_name IN ({placeholders})",
            list(aliases_set)
        )
        candidates = cursor.fetchall()

        for cand_row in candidates:
            cand_id = cand_row["candidate_id"]
            logger.info("Migrating unresolved candidate (id=%s) to target person_id=%s", cand_id, target_person_id)

            cursor.execute(
                "SELECT summary_id, note, display_order FROM summary_person_candidates WHERE candidate_id = ?",
                (cand_id,)
            )
            links = cursor.fetchall()

            for link in links:
                summary_id = link["summary_id"]
                cand_note = link["note"]
                cand_order = link["display_order"]

                # Check if there is already a link in summary_people for this target_person_id
                cursor.execute(
                    "SELECT note, display_order FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, target_person_id)
                )
                existing_link = cursor.fetchone()

                if existing_link is not None:
                    # Merge notes and keep minimum display order safely
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
                        (merged_note, merged_order, summary_id, target_person_id)
                    )
                    # Delete old candidate link
                    conn.execute(
                        "DELETE FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                        (summary_id, cand_id)
                    )
                else:
                    # Simply insert new summary_people link
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, target_person_id, cand_note, cand_order)
                    )
                    # Delete old candidate link
                    conn.execute(
                        "DELETE FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                        (summary_id, cand_id)
                    )

            # Delete migrated candidate
            conn.execute("DELETE FROM person_candidates WHERE candidate_id = ?", (cand_id,))

        # Step C: Match and migrate old duplicate 'people' records (vault_id IS NULL)
        cursor.execute(
            f"SELECT person_id FROM people WHERE vault_id IS NULL AND normalized_name IN ({placeholders})",
            list(aliases_set)
        )
        old_people = cursor.fetchall()

        for old_p_row in old_people:
            old_person_id = old_p_row["person_id"]

            if old_person_id == target_person_id:
                continue

            logger.info("Migrating old duplicate person (id=%s) to target person_id=%s", old_person_id, target_person_id)

            cursor.execute(
                "SELECT summary_id, note, display_order FROM summary_people WHERE person_id = ?",
                (old_person_id,)
            )
            old_links = cursor.fetchall()

            for old_link in old_links:
                summary_id = old_link["summary_id"]
                old_note = old_link["note"]
                old_order = old_link["display_order"]

                # Check if there is already a link for target_person_id
                cursor.execute(
                    "SELECT note, display_order FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, target_person_id)
                )
                existing_link = cursor.fetchone()

                if existing_link is not None:
                    # Merge notes and keep minimum display order safely
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
                        (merged_note, merged_order, summary_id, target_person_id)
                    )
                    # Delete the old link
                    conn.execute(
                        "DELETE FROM summary_people WHERE summary_id = ? AND person_id = ?",
                        (summary_id, old_person_id)
                    )
                else:
                    # Move link to the target_person_id directly
                    conn.execute(
                        "UPDATE summary_people SET person_id = ? WHERE summary_id = ? AND person_id = ?",
                        (target_person_id, summary_id, old_person_id)
                    )

            # Delete migrated obsolete people row
            conn.execute("DELETE FROM people WHERE person_id = ?", (old_person_id,))

        # Run final deferred target row update after Step C has cleared all duplicates
        if needs_final_update:
            conn.execute(final_update_sql, final_update_args)


def main() -> None:
    # 1. Load and validate people notes first
    logger.info("Starting sync of people from Vault notes...")
    people_notes_map = load_and_validate_people_notes()

    conn = memory.get_db_connection()
    try:
        with conn:
            sync_people_in_tx(conn, people_notes_map)
        logger.info("People sync completed successfully.")
    except Exception as e:
        logger.exception("Failed to sync people from Vault notes")
        raise
    finally:
        conn.close()
