import json
from pathlib import Path

import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub.summary import migration
from obsidian_ai_hub.summary import store


def _write_jsonl(base_dir: Path, relative_path: str, records: list[dict]) -> Path:
    file_path = base_dir / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return file_path


def _make_day_record(date_str: str, summary: str = "Day summary") -> dict:
    return {
        "schema_version": 1,
        "date": date_str,
        "generated_at": f"{date_str}T22:00:00",
        "summary": summary,
        "topics": ["LLM・AI活用"],
        "activities": ["Activity 1"],
        "learnings": ["Learning 1"],
        "reflections": ["Reflection 1"],
        "gratitude": ["Gratitude 1"],
        "people": [{"name": "Alice", "note": "note"}],
        "questions": ["Q1"],
        "keywords": ["keyword"],
        "next_actions": ["A1"],
        "mood": "good",
        "sleep": "7h30m",
        "source_stats": {"activity_count": 1},
    }


def _make_week_record(week_id: str, summary: str = "Week summary") -> dict:
    return {
        "schema_version": 1,
        "week_id": week_id,
        "week_start_date": "2026-07-13",
        "week_end_date": "2026-07-19",
        "generated_at": "2026-07-19T22:00:00",
        "summary": summary,
        "topics": ["信仰・聖書"],
        "activities": ["Week activity"],
        "learnings": ["Week learning"],
        "reflections": ["Week reflection"],
        "gratitude": ["Week gratitude"],
        "people": [{"name": "Bob", "note": ""}],
        "questions": ["Q2"],
        "keywords": ["week-keyword"],
        "next_actions": ["A2"],
        "mood": "neutral",
        "sleep": "7.0",
        "source_stats": {"daily_record_count": 7},
    }


def _make_month_record(month: str, summary: str = "Month summary") -> dict:
    return {
        "schema_version": 1,
        "month": month,
        "generated_at": "2026-07-31T22:00:00",
        "summary": summary,
        "topics": ["健康・医療"],
        "activities": ["Month activity"],
        "learnings": ["Month learning"],
        "reflections": ["Month reflection"],
        "gratitude": ["Month gratitude"],
        "people": [{"name": "Carol", "note": ""}],
        "questions": ["Q3"],
        "keywords": ["month-keyword"],
        "next_actions": ["A3"],
        "mood": "good",
        "sleep": "7.5",
        "source_stats": {"weekly_record_count": 4},
    }


def test_basic_migration(test_memory_db_path, tmp_path):
    activity_path = tmp_path / "activity"
    _write_jsonl(activity_path, "2026/07/2026-07.jsonl", [_make_day_record("2026-07-17")])
    _write_jsonl(activity_path, "2026/2026-week.jsonl", [_make_week_record("2026-W29")])
    _write_jsonl(activity_path, "2026/2026.jsonl", [_make_month_record("2026-07")])

    conn = memory.get_db_connection()
    try:
        stats = migration.run_migration(activity_path, conn)
        assert stats["files"] == 3
        assert stats["added"] == 3
        assert stats["updated"] == 0
        assert stats["invalid"] == 0
        assert stats["duplicates"] == 0

        day = store.get_summary_by_period("day", "2026-07-17", conn=conn)
        assert day["summary"] == "Day summary"
        assert day["mood"] == "good"
        assert day["sleep_hours"] == 7.5
        assert any(i["kind"] == "activities" for i in day["items"])
        assert day["topics"] == ["LLM・AI活用"]
        assert day["people"][0]["name"] == "Alice"

        week = store.get_summary_by_period("week", "2026-W29", conn=conn)
        assert week["summary"] == "Week summary"
        assert week["mood"] is None
        assert week["sleep_hours"] is None
        assert any(i["kind"] == "progress" for i in week["items"])
        assert not any(i["kind"] == "activities" for i in week["items"])

        month = store.get_summary_by_period("month", "2026-07", conn=conn)
        assert month["summary"] == "Month summary"
        assert month["mood"] is None
        assert month["sleep_hours"] is None
        assert any(i["kind"] == "progress" for i in month["items"])
    finally:
        conn.close()


def test_idempotent(test_memory_db_path, tmp_path):
    activity_path = tmp_path / "activity"
    _write_jsonl(activity_path, "2026/07/2026-07.jsonl", [_make_day_record("2026-07-17")])

    conn = memory.get_db_connection()
    try:
        stats1 = migration.run_migration(activity_path, conn)
        assert stats1["added"] == 1

        first = store.get_summary_by_period("day", "2026-07-17", conn=conn)

        stats2 = migration.run_migration(activity_path, conn)
        assert stats2["added"] == 0
        assert stats2["invalid"] == 0

        second = store.get_summary_by_period("day", "2026-07-17", conn=conn)
        assert first["summary_id"] == second["summary_id"]
        assert first["summary"] == second["summary"]
        assert first["items"] == second["items"]
    finally:
        conn.close()


def test_invalid_json_skipped(test_memory_db_path, tmp_path):
    activity_path = tmp_path / "activity"
    _write_jsonl(activity_path, "2026/07/2026-07.jsonl", [
        _make_day_record("2026-07-17"),
        "not valid json",
        _make_day_record("2026-07-18"),
    ])

    conn = memory.get_db_connection()
    try:
        stats = migration.run_migration(activity_path, conn)
        assert stats["added"] == 2
        assert stats["invalid"] == 1
    finally:
        conn.close()


def test_duplicate_period_key_last_wins(test_memory_db_path, tmp_path):
    activity_path = tmp_path / "activity"
    _write_jsonl(activity_path, "2026/07/2026-07.jsonl", [
        _make_day_record("2026-07-17", summary="First"),
        _make_day_record("2026-07-17", summary="Last"),
    ])

    conn = memory.get_db_connection()
    try:
        stats = migration.run_migration(activity_path, conn)
        assert stats["added"] == 1
        assert stats["updated"] == 1
        assert stats["duplicates"] == 1

        day = store.get_summary_by_period("day", "2026-07-17", conn=conn)
        assert day["summary"] == "Last"
    finally:
        conn.close()


def test_historical_new_fields_empty(test_memory_db_path, tmp_path):
    activity_path = tmp_path / "activity"
    _write_jsonl(activity_path, "2026/07/2026-07.jsonl", [_make_day_record("2026-07-17")])
    _write_jsonl(activity_path, "2026/2026-week.jsonl", [_make_week_record("2026-W29")])
    _write_jsonl(activity_path, "2026/2026.jsonl", [_make_month_record("2026-07")])

    conn = memory.get_db_connection()
    try:
        migration.run_migration(activity_path, conn)

        day = store.get_summary_by_period("day", "2026-07-17", conn=conn)
        assert not any(i["kind"] == "highlights" for i in day["items"])

        week = store.get_summary_by_period("week", "2026-W29", conn=conn)
        assert not any(i["kind"] in ("highlights", "patterns") for i in week["items"])

        month = store.get_summary_by_period("month", "2026-07", conn=conn)
        assert not any(i["kind"] in ("highlights", "patterns", "changes") for i in month["items"])
    finally:
        conn.close()
