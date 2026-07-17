"""CLI entry point: migrate activity JSONL files to SQLite.

Usage: uv run python scripts/migrate_activity_jsonl_to_sqlite.py
"""

import logging

from obsidian_ai_hub.activity.migration import main

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
