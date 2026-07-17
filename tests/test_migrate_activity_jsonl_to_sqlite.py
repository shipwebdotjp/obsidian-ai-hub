from __future__ import annotations

import json
from pathlib import Path

import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub.activity import migration
from obsidian_ai_hub.activity import store
from obsidian_ai_hub.utils import config as app_config


def _write_jsonl(
    base_dir: Path,
    date_str: str,
    records: list[dict],
) -> Path:
    """Create a daily JSONL file for the given date. Returns the file path."""
    year, month, _ = date_str.split("-")
    log_dir = base_dir / year / month
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date_str}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return log_file


class TestDiscovery:
    def test_discovers_daily_jsonl_only(self, tmp_path: Path):
        activity_path = tmp_path / "activity"
        _write_jsonl(activity_path, "2026-07-20", [{"summary": "a"}])
        _write_jsonl(activity_path, "2026-07-21", [{"summary": "b"}])
        # Monthly summary (should be excluded)
        monthly = activity_path / "2026" / "07" / "2026-07.jsonl"
        monthly.parent.mkdir(parents=True, exist_ok=True)
        monthly.write_text("[]\n")

        files = migration.discover_jsonl_files(activity_path)
        assert len(files) == 2
        assert all(f.name.count("-") == 2 for f in files)

    def test_empty_directory(self, tmp_path: Path):
        activity_path = tmp_path / "activity"
        activity_path.mkdir()
        assert migration.discover_jsonl_files(activity_path) == []

    def test_missing_directory(self, tmp_path: Path):
        activity_path = tmp_path / "nonexistent"
        assert migration.discover_jsonl_files(activity_path) == []


class TestParseLine:
    def test_happy_path(self):
        line = '{"timestamp": "2026-07-20T10:00:00", "app_name": "Safari", "window_title": "Google", "summary": "検索", "category": "調査", "keywords": ["web"], "screenshots": ["/tmp/shot.png"]}'
        record = migration.parse_line(line, 1, "2026-07-20", "2026/07/2026-07-20.jsonl")
        assert record is not None
        assert record["activity_date"] == "2026-07-20"
        assert record["occurred_at"] == "2026-07-20T10:00:00"
        assert record["app_name"] == "Safari"
        assert record["window_title"] == "Google"
        assert record["summary"] == "検索"
        assert record["category"] == "調査"
        assert json.loads(record["keywords"]) == ["web"]
        assert json.loads(record["screenshots"]) == ["/tmp/shot.png"]
        assert record["source_path"] == "2026/07/2026-07-20.jsonl"
        assert record["source_line"] == 1
        assert record["activity_id"].startswith("act_")

    def test_missing_fields_default_to_empty(self):
        line = '{"timestamp": "2026-07-20T10:00:00", "summary": "test"}'
        record = migration.parse_line(line, 1, "2026-07-20", "file.jsonl")
        assert record is not None
        assert record["app_name"] is None
        assert record["window_title"] is None
        assert record["category"] == "その他"
        assert json.loads(record["keywords"]) == []
        assert json.loads(record["screenshots"]) == []

    def test_malformed_json_returns_none(self):
        record = migration.parse_line("{invalid json}", 1, "2026-07-20", "file.jsonl")
        assert record is None

    def test_non_object_json_returns_none(self):
        record = migration.parse_line('"just a string"', 1, "2026-07-20", "file.jsonl")
        assert record is None

    def test_null_fields_coerced(self):
        line = '{"timestamp": "2026-07-20T10:00:00", "summary": "t", "category": null, "keywords": null, "screenshots": null}'
        record = migration.parse_line(line, 1, "2026-07-20", "file.jsonl")
        assert record is not None
        assert record["category"] == "その他"
        assert json.loads(record["keywords"]) == []
        assert json.loads(record["screenshots"]) == []


class TestMigration:
    def _setup_activity(self, tmp_path: Path) -> Path:
        activity_path = tmp_path / "activity"
        activity_path.mkdir()
        _write_jsonl(activity_path, "2026-07-20", [
            {"timestamp": "2026-07-20T10:00:00", "app_name": "Safari", "summary": "検索", "category": "調査", "keywords": ["web"]},
            {"timestamp": "2026-07-20T11:00:00", "app_name": "Code", "summary": "コーディング", "category": "開発", "keywords": ["python"]},
        ])
        _write_jsonl(activity_path, "2026-07-21", [
            {"timestamp": "2026-07-21T09:00:00", "app_name": "Slack", "summary": "チャット", "category": "コミュニケーション", "keywords": []},
        ])
        return activity_path

    def test_basic_migration(self, test_memory_db_path: Path, monkeypatch, tmp_path: Path):
        activity_path = self._setup_activity(tmp_path)
        conn = memory.get_db_connection()
        try:
            stats = migration.run_migration(activity_path, conn)
            conn.commit()
        finally:
            conn.close()

        assert stats["files"] == 2
        assert stats["added"] == 3
        assert stats["skipped"] == 0
        assert stats["invalid"] == 0

        # Verify data
        acts = store.get_activities_by_date("2026-07-20")
        assert len(acts) == 2
        assert acts[0]["app_name"] == "Safari"
        assert acts[0]["keywords"] == ["web"]
        assert acts[1]["app_name"] == "Code"

        acts21 = store.get_activities_by_date("2026-07-21")
        assert len(acts21) == 1
        assert acts21[0]["app_name"] == "Slack"

    def test_idempotent(self, test_memory_db_path: Path, monkeypatch, tmp_path: Path):
        activity_path = self._setup_activity(tmp_path)

        conn = memory.get_db_connection()
        try:
            stats1 = migration.run_migration(activity_path, conn)
            conn.commit()

            stats2 = migration.run_migration(activity_path, conn)
            conn.commit()
        finally:
            conn.close()

        assert stats1["added"] == 3
        assert stats2["added"] == 0
        assert stats2["skipped"] == 3

    def test_skips_malformed_json(self, test_memory_db_path: Path, monkeypatch, tmp_path: Path):
        activity_path = tmp_path / "activity"
        activity_path.mkdir()
        _write_jsonl(activity_path, "2026-07-20", [
            {"timestamp": "2026-07-20T10:00:00", "summary": "valid"},
            "{invalid json}",
            {"timestamp": "2026-07-20T11:00:00", "summary": "also valid"},
        ])

        conn = memory.get_db_connection()
        try:
            stats = migration.run_migration(activity_path, conn)
            conn.commit()
        finally:
            conn.close()

        assert stats["added"] == 2
        assert stats["invalid"] == 1

        acts = store.get_activities_by_date("2026-07-20")
        assert len(acts) == 2

    def test_missing_timestamp(self, test_memory_db_path: Path, monkeypatch, tmp_path: Path):
        activity_path = tmp_path / "activity"
        activity_path.mkdir()
        _write_jsonl(activity_path, "2026-07-20", [
            {"summary": "no timestamp"},
        ])

        conn = memory.get_db_connection()
        try:
            stats = migration.run_migration(activity_path, conn)
            conn.commit()
        finally:
            conn.close()

        assert stats["added"] == 1

        acts = store.get_activities_by_date("2026-07-20")
        assert acts[0]["occurred_at"] == ""

    def test_source_path_and_line_preserved(self, test_memory_db_path: Path, monkeypatch, tmp_path: Path):
        activity_path = tmp_path / "activity"
        activity_path.mkdir()
        _write_jsonl(activity_path, "2026-07-20", [
            {"timestamp": "2026-07-20T10:00:00", "summary": "line1"},
            {"timestamp": "2026-07-20T11:00:00", "summary": "line2"},
        ])

        conn = memory.get_db_connection()
        try:
            migration.run_migration(activity_path, conn)
            conn.commit()
        finally:
            conn.close()

        acts = store.get_activities_by_date("2026-07-20", conn=memory.get_db_connection())
        assert len(acts) == 2
        assert acts[0]["source_path"] == "2026/07/2026-07-20.jsonl"
        assert acts[0]["source_line"] == 1
        assert acts[1]["source_line"] == 2

    def test_skips_monthly_summary_file(self, test_memory_db_path: Path, monkeypatch, tmp_path: Path):
        activity_path = tmp_path / "activity"
        activity_path.mkdir()
        _write_jsonl(activity_path, "2026-07-20", [{"summary": "daily"}])
        # Monthly summary — one hyphen
        monthly = activity_path / "2026" / "07" / "2026-07.jsonl"
        monthly.parent.mkdir(parents=True, exist_ok=True)
        monthly.write_text('{"date": "2026-07-20", "summary": "monthly"}\n')

        conn = memory.get_db_connection()
        try:
            stats = migration.run_migration(activity_path, conn)
            conn.commit()
        finally:
            conn.close()

        assert stats["files"] == 1
        assert stats["added"] == 1

        acts = store.get_activities_by_date("2026-07-20")
        assert len(acts) == 1
        assert acts[0]["summary"] == "daily"
