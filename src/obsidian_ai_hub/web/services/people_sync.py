from typing import Any

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.people_sync.sync import get_db_vault_conflicts_report
from obsidian_ai_hub.utils.people_loader import load_people_notes_with_report


def sync_people() -> dict[str, Any]:
    conn = get_db_connection()
    try:
        people_notes_map, report = load_people_notes_with_report(conn)
        parsed_notes = report.get("parsed_notes", [])

        with conn:
            # 1. Detect conflicts
            db_conflicts = get_db_vault_conflicts_report(conn, parsed_notes)

            # 2. Sync safe part
            from obsidian_ai_hub.people_sync.sync import sync_people_in_tx

            skipped_relation_merges, prop_summary = sync_people_in_tx(
                conn, people_notes_map, report.get("property_report")
            )

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
                "skipped_relation_merges": skipped_relation_merges,
                "property_report": prop_summary,
            }
    finally:
        conn.close()


def get_vault_report_dynamic() -> dict[str, Any]:
    conn = get_db_connection()
    try:
        people_notes_map, report = load_people_notes_with_report(conn)
        parsed_notes = report.get("parsed_notes", [])

        db_conflicts = get_db_vault_conflicts_report(conn, parsed_notes)
        clean_loader_report = {
            "file_deficiencies": report.get("file_deficiencies", []),
            "duplicate_ids": report.get("duplicate_ids", []),
            "normalized_name_collisions": report.get("normalized_name_collisions", []),
            "alias_collisions": report.get("alias_collisions", []),
        }
        prop_report = {
            "replaced_properties_count": 0,
            "replaced_values_count": 0,
            "deleted_properties_count": 0,
            "deleted_values_count": 0,
            "invalid_properties": report.get("property_report", {}).get(
                "invalid_properties", []
            ),
            "skipped_property_merges": [],
        }
        # Read-only report: no sync is performed here, so synced is always False.
        # sync_people() reports True because it actually applied the sync.
        return {
            "synced": False,
            "loader_report": clean_loader_report,
            "db_conflicts": db_conflicts,
            "skipped_relation_merges": [],
            "property_report": prop_report,
        }
    finally:
        conn.close()
