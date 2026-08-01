from typing import Any

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.people_sync.sync import get_db_vault_conflicts_report
from obsidian_ai_hub.utils.people_loader import load_people_notes_with_report


def sync_people() -> dict[str, Any]:
    people_notes_map, report = load_people_notes_with_report()
    parsed_notes = report.get("parsed_notes", [])

    conn = get_db_connection()
    try:
        with conn:
            # 1. Detect conflicts
            db_conflicts = get_db_vault_conflicts_report(conn, parsed_notes)

            # 2. Sync safe part
            from obsidian_ai_hub.people_sync.sync import sync_people_in_tx

            sync_people_in_tx(conn, people_notes_map)

            # Return reports
            clean_loader_report = {
                "file_deficiencies": report.get("file_deficiencies", []),
                "duplicate_ids": report.get("duplicate_ids", []),
                "normalized_name_collisions": report.get(
                    "normalized_name_collisions", []
                ),
                "alias_collisions": report.get("alias_collisions", []),
            }
            return {
                "synced": True,
                "loader_report": clean_loader_report,
                "db_conflicts": db_conflicts,
            }
    finally:
        conn.close()


def get_vault_report_dynamic() -> dict[str, Any]:
    people_notes_map, report = load_people_notes_with_report()
    parsed_notes = report.get("parsed_notes", [])

    conn = get_db_connection()
    try:
        db_conflicts = get_db_vault_conflicts_report(conn, parsed_notes)
        clean_loader_report = {
            "file_deficiencies": report.get("file_deficiencies", []),
            "duplicate_ids": report.get("duplicate_ids", []),
            "normalized_name_collisions": report.get("normalized_name_collisions", []),
            "alias_collisions": report.get("alias_collisions", []),
        }
        return {"loader_report": clean_loader_report, "db_conflicts": db_conflicts}
    finally:
        conn.close()
