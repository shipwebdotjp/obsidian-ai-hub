from __future__ import annotations

import json
import logging
import sqlite3
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any

from obsidian_ai_hub.memory import get_db_connection
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.utils.topics import normalize_topics

logger = logging.getLogger(__name__)

DAILY_KIND_ORDER = ["highlights", "activities", "learnings", "reflections", "gratitude"]
WEEKLY_KIND_ORDER = ["highlights", "progress", "learnings", "reflections", "patterns", "gratitude"]
MONTHLY_KIND_ORDER = ["highlights", "progress", "changes", "learnings", "reflections", "patterns", "gratitude"]

KIND_MAP = {
    "day": {
        "activities": "activities",
        "learnings": "learnings",
        "reflections": "reflections",
        "gratitude": "gratitude",
    },
    "week": {
        "activities": "progress",
        "learnings": "learnings",
        "reflections": "reflections",
        "gratitude": "gratitude",
    },
    "month": {
        "activities": "progress",
        "learnings": "learnings",
        "reflections": "reflections",
        "gratitude": "gratitude",
    },
}


def _month_bounds(month_key: str) -> tuple[str, str]:
    year, month = map(int, month_key.split("-"))
    _, last_day = monthrange(year, month)
    return (
        date(year, month, 1).strftime("%Y-%m-%d"),
        date(year, month, last_day).strftime("%Y-%m-%d"),
    )


def _week_bounds(week_record: dict) -> tuple[str, str]:
    return (
        week_record.get("week_start_date") or "",
        week_record.get("week_end_date") or "",
    )


def _coerce_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    return []


def _coerce_string_list(value: Any) -> list[str]:
    items = _coerce_list(value)
    return [str(item) for item in items if item is not None and str(item).strip()]


def _build_items(period_type: str, data: dict) -> list[dict]:
    kind_map = KIND_MAP[period_type]
    kind_order = {"day": DAILY_KIND_ORDER, "week": WEEKLY_KIND_ORDER, "month": MONTHLY_KIND_ORDER}[period_type]

    raw = {}
    for old_kind, new_kind in kind_map.items():
        entries = _coerce_string_list(data.get(old_kind))
        if entries:
            raw[new_kind] = entries

    items: list[dict] = []
    for order, kind in enumerate(kind_order):
        bodies = raw.get(kind, [])
        if bodies:
            items.append({
                "kind": kind,
                "body": "\n".join(f"- {b}" for b in bodies),
                "display_order": order,
            })
    return items


def parse_record(
    line: str,
    line_no: int,
    period_type: str,
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

    if period_type == "day":
        period_key = data.get("date")
        if not period_key:
            logger.warning("Missing date at %s:%d", source_path, line_no)
            return None
        period_start = period_key
        period_end = period_key
    elif period_type == "week":
        period_key = data.get("week_id")
        if not period_key:
            logger.warning("Missing week_id at %s:%d", source_path, line_no)
            return None
        period_start, period_end = _week_bounds(data)
    elif period_type == "month":
        period_key = data.get("month")
        if not period_key:
            logger.warning("Missing month at %s:%d", source_path, line_no)
            return None
        period_start, period_end = _month_bounds(period_key)
    else:
        logger.warning("Unknown period_type %r at %s:%d", period_type, source_path, line_no)
        return None

    topics = normalize_topics(_coerce_list(data.get("topics")))
    people = []
    for person in _coerce_list(data.get("people")):
        if isinstance(person, dict) and person.get("name"):
            people.append({"name": str(person["name"]), "note": str(person.get("note", ""))})

    record = {
        "period_type": period_type,
        "period_key": period_key,
        "period_start": period_start,
        "period_end": period_end,
        "generated_at": data.get("generated_at") or "",
        "summary": data.get("summary"),
        "keywords": _coerce_string_list(data.get("keywords")),
        "topics": topics,
        "projects": [],
        "people": people,
        "items": _build_items(period_type, data),
    }

    if period_type == "day":
        record["mood"] = data.get("mood")
        sleep_raw = data.get("sleep")
        record["sleep_raw"] = sleep_raw
        record["sleep_hours"] = summary_store.parse_sleep_hours(sleep_raw)
    else:
        record["mood"] = None
        record["sleep_raw"] = None
        record["sleep_hours"] = None

    return record


def discover_summary_jsonl_files(activity_path: Path) -> list[tuple[Path, str]]:
    """Return list of (file_path, period_type) tuples."""
    if not activity_path.exists():
        return []

    files: list[tuple[Path, str]] = []
    for year_dir in sorted(activity_path.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue

        # Daily files: YYYY/MM/YYYY-MM.jsonl
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            for f in sorted(month_dir.iterdir()):
                if not f.is_file() or f.suffix != ".jsonl":
                    continue
                stem = f.stem
                parts = stem.split("-")
                if len(parts) != 2:
                    continue
                try:
                    date(int(parts[0]), int(parts[1]), 1)
                except (ValueError, OverflowError):
                    continue
                if parts[0] != year_dir.name or parts[1] != month_dir.name:
                    continue
                files.append((f, "day"))

        # Weekly files: YYYY/YYYY-week.jsonl
        weekly_file = year_dir / f"{year_dir.name}-week.jsonl"
        if weekly_file.is_file():
            files.append((weekly_file, "week"))

        # Monthly files: YYYY/YYYY.jsonl
        monthly_file = year_dir / f"{year_dir.name}.jsonl"
        if monthly_file.is_file():
            files.append((monthly_file, "month"))

    return files


def migrate_file(
    file_path: Path,
    relative_path: str,
    period_type: str,
    conn: sqlite3.Connection,
) -> tuple[int, int, int, int]:
    added = 0
    updated = 0
    invalid = 0
    duplicates = 0
    seen_periods: set[str] = set()

    with open(file_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            record = parse_record(line, line_no, period_type, relative_path)
            if record is None:
                invalid += 1
                continue

            period_key = record["period_key"]
            if period_key in seen_periods:
                duplicates += 1
            seen_periods.add(period_key)

            try:
                existing = summary_store.get_summary_by_period(
                    record["period_type"], period_key, conn=conn
                )
                summary_store.upsert_summary(record, conn=conn)
                if existing is None:
                    added += 1
                else:
                    updated += 1
            except sqlite3.Error as exc:
                logger.error("SQLite error at %s:%d: %s", relative_path, line_no, exc)
                raise

    return added, updated, invalid, duplicates


def run_migration(activity_path: Path, conn: sqlite3.Connection) -> dict:
    files = discover_summary_jsonl_files(activity_path)
    total_added = 0
    total_updated = 0
    total_invalid = 0
    total_duplicates = 0

    for file_path, period_type in files:
        relative = file_path.relative_to(activity_path).as_posix()
        added, updated, invalid, duplicates = migrate_file(file_path, relative, period_type, conn)
        total_added += added
        total_updated += updated
        total_invalid += invalid
        total_duplicates += duplicates

    return {
        "files": len(files),
        "added": total_added,
        "updated": total_updated,
        "invalid": total_invalid,
        "duplicates": total_duplicates,
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
        print(f"更新件数: {stats['updated']}")
        print(f"不正行数: {stats['invalid']}")
        print(f"重複件数: {stats['duplicates']}")
    except Exception:
        conn.rollback()
        logger.exception("Migration failed, rolling back")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
