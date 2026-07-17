from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any, Dict

from obsidian_ai_hub import memory
from obsidian_ai_hub.utils.people_loader import load_and_validate_people_notes
from obsidian_ai_hub.summary.store import normalize_entity_name

logger = logging.getLogger(__name__)


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
        if row is not None:
            target_person_id = row[0]
            # Update name and normalized_name if they changed
            conn.execute(
                "UPDATE people SET display_name = ?, normalized_name = ? WHERE person_id = ?",
                (vault_name, normalized_vault_name, target_person_id),
            )
        else:
            # Check if there is an existing person with the same normalized name
            cursor.execute("SELECT person_id FROM people WHERE normalized_name = ?", (normalized_vault_name,))
            row = cursor.fetchone()
            if row is not None:
                target_person_id = row[0]
                conn.execute(
                    "UPDATE people SET vault_id = ?, display_name = ? WHERE person_id = ?",
                    (vault_id, vault_name, target_person_id),
                )
            else:
                # Create a new resolved person row
                target_person_id = f"peo_{uuid.uuid4().hex}"
                conn.execute(
                    "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES (?, ?, ?, ?)",
                    (target_person_id, normalized_vault_name, vault_name, vault_id),
                )

        logger.info("Resolved person '%s' to person_id=%s with vault_id=%s", vault_name, target_person_id, vault_id)

        # Step B: Match and migrate unresolved candidates
        # Find candidates matching any of aliases_set
        placeholders = ", ".join("?" for _ in aliases_set)
        cursor.execute(
            f"SELECT candidate_id, display_name FROM person_candidates WHERE normalized_name IN ({placeholders})",
            list(aliases_set)
        )
        candidates = cursor.fetchall()

        for cand_row in candidates:
            cand_id = cand_row["candidate_id"]
            cand_display_name = cand_row["display_name"]
            logger.info("Migrating unresolved candidate '%s' (id=%s) to '%s'", cand_display_name, cand_id, vault_name)

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
                    # Merge notes and keep minimum display order
                    notes_to_join = []
                    existing_note = existing_link["note"]
                    existing_order = existing_link["display_order"]

                    if existing_note and existing_note.strip():
                        notes_to_join.append(existing_note.strip())
                    if cand_note and cand_note.strip():
                        notes_to_join.append(cand_note.strip())

                    merged_note = "\n".join(notes_to_join) if notes_to_join else None
                    merged_order = min(existing_order, cand_order)

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
            f"SELECT person_id, display_name FROM people WHERE vault_id IS NULL AND normalized_name IN ({placeholders})",
            list(aliases_set)
        )
        old_people = cursor.fetchall()

        for old_p_row in old_people:
            old_person_id = old_p_row["person_id"]
            old_display_name = old_p_row["display_name"]

            if old_person_id == target_person_id:
                continue

            logger.info("Migrating old duplicate person '%s' (id=%s) to '%s'", old_display_name, old_person_id, vault_name)

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
                    # Merge notes and keep minimum display order
                    notes_to_join = []
                    existing_note = existing_link["note"]
                    existing_order = existing_link["display_order"]

                    if existing_note and existing_note.strip():
                        notes_to_join.append(existing_note.strip())
                    if old_note and old_note.strip():
                        notes_to_join.append(old_note.strip())

                    merged_note = "\n".join(notes_to_join) if notes_to_join else None
                    merged_order = min(existing_order, old_order)

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
