from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import date
from pathlib import Path

from obsidian_ai_hub.memory import get_db_connection
from obsidian_ai_hub.utils import config as app_config

logger = logging.getLogger(__name__)


def discover_jsonl_files(activity_path: Path) -> list[Path]:
    if not activity_path.exists():
        return []

    files: list[Path] = []
    for year_dir in sorted(activity_path.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            for f in sorted(month_dir.iterdir()):
                if not f.is_file() or f.suffix != ".jsonl":
                    continue
                stem = f.stem
                parts = stem.split("-")
                if len(parts) != 3:
                    continue
                try:
                    d = date(int(parts[0]), int(parts[1]), int(parts[2]))
                except (ValueError, OverflowError):
                    continue
                if parts[0] != year_dir.name or parts[1] != month_dir.name:
                    continue
                files.append(f)
    return files


def parse_line(
    line: str,
    line_no: int,
    activity_date: str,
    source_path: str,
) -> dict | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON at %s:%d", source_path, line_no)
        return None

    if not isinstance(data, dict):
        logger.warning("Non-object JSON at %s:%d", source_path, line_no)
        return None

    timestamp = data.get("timestamp")
    if not timestamp or not isinstance(timestamp, str) or not timestamp.strip():
        logger.warning("Missing or invalid timestamp at %s:%d", source_path, line_no)
        return None

    keywords = data.get("keywords")
    if not isinstance(keywords, list):
        keywords = []
    screenshots = data.get("screenshots")
    if not isinstance(screenshots, list):
        screenshots = []

    return {
        "activity_id": f"act_{uuid.uuid4().hex}",
        "activity_date": activity_date,
        "occurred_at": timestamp,
        "app_name": data.get("app_name"),
        "window_title": data.get("window_title"),
        "summary": data.get("summary", ""),
        "category": data.get("category") or "その他",
        "keywords": json.dumps(keywords, ensure_ascii=False),
        "screenshots": json.dumps(screenshots, ensure_ascii=False),
        "source_path": source_path,
        "source_line": line_no,
    }


def migrate_file(
    file_path: Path,
    relative_path: str,
    activity_date: str,
    conn: sqlite3.Connection,
) -> tuple[int, int, int]:
    added = 0
    skipped = 0
    invalid = 0

    with open(file_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            record = parse_line(line, line_no, activity_date, relative_path)
            if record is None:
                invalid += 1
                continue

            try:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO activity_logs
                        (schema_version, activity_id, activity_date, occurred_at,
                         app_name, window_title, summary, category,
                         keywords, screenshots, source_path, source_line)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record["activity_id"],
                        record["activity_date"],
                        record["occurred_at"],
                        record["app_name"],
                        record["window_title"],
                        record["summary"],
                        record["category"],
                        record["keywords"],
                        record["screenshots"],
                        record["source_path"],
                        record["source_line"],
                    ),
                )
                if cursor.rowcount > 0:
                    added += 1
                else:
                    skipped += 1
            except sqlite3.Error as exc:
                logger.error("SQLite error at %s:%d: %s", relative_path, line_no, exc)
                raise

    return added, skipped, invalid


def run_migration(activity_path: Path, conn: sqlite3.Connection) -> dict:
    files = discover_jsonl_files(activity_path)
    total_added = 0
    total_skipped = 0
    total_invalid = 0

    for file_path in files:
        relative = file_path.relative_to(activity_path).as_posix()
        activity_date = file_path.stem
        added, skipped, invalid = migrate_file(file_path, relative, activity_date, conn)
        total_added += added
        total_skipped += skipped
        total_invalid += invalid

    return {
        "files": len(files),
        "added": total_added,
        "skipped": total_skipped,
        "invalid": total_invalid,
    }


def main() -> None:
    activity_path = app_config.ACTIVITY_PATH
    if not activity_path.exists():
        print(f"ACTIVITY_PATH not found: {activity_path}")
        return

    conn = get_db_connection()
    try:
        conn.execute("BEGIN")
        stats = run_migration(activity_path, conn)
        conn.commit()
        print(f"走査ファイル数: {stats['files']}")
        print(f"追加件数: {stats['added']}")
        print(f"既取込スキップ数: {stats['skipped']}")
        print(f"不正行数: {stats['invalid']}")
    except Exception:
        conn.rollback()
        logger.exception("Migration failed, rolling back")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
