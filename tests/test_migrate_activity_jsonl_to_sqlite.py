from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub.activity import migration


def _write_jsonl(base_dir: Path, date_str: str, records: list[dict]) -> Path:
    year, month, _ = date_str.split("-")
    log_dir = base_dir / year / month
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date_str}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return log_file


class TestMigration:
    def test_basic_migration(self, test_memory_db_path: Path, tmp_path: Path):
        activity_path = tmp_path / "activity"
        activity_path.mkdir()
        _write_jsonl(
            activity_path,
            "2026-07-20",
            [
                {
                    "timestamp": "2026-07-20T10:00:00",
                    "app_name": "Safari",
                    "summary": "検索",
                    "category": "調査",
                    "keywords": ["web"],
                },
                {
                    "timestamp": "2026-07-20T11:00:00",
                    "app_name": "Code",
                    "summary": "コーディング",
                    "category": "開発",
                },
            ],
        )
        _write_jsonl(
            activity_path,
            "2026-07-21",
            [
                {
                    "timestamp": "2026-07-21T09:00:00",
                    "app_name": "Slack",
                    "summary": "チャット",
                },
            ],
        )

        conn = memory.get_db_connection()
        try:
            stats = migration.run_migration(activity_path, conn)
            conn.commit()
        finally:
            conn.close()

        assert stats["files"] == 2
        assert stats["added"] == 3
        assert stats["invalid"] == 0

    def test_idempotent(self, test_memory_db_path: Path, tmp_path: Path):
        activity_path = tmp_path / "activity"
        activity_path.mkdir()
        _write_jsonl(
            activity_path,
            "2026-07-20",
            [
                {"timestamp": "2026-07-20T10:00:00", "summary": "a"},
            ],
        )

        conn = memory.get_db_connection()
        try:
            s1 = migration.run_migration(activity_path, conn)
            conn.commit()
            s2 = migration.run_migration(activity_path, conn)
            conn.commit()
        finally:
            conn.close()

        assert s1["added"] == 1
        assert s2["added"] == 0
        assert s2["skipped"] == 1

    def test_database_error_rollback(self, test_memory_db_path: Path, tmp_path: Path):
        activity_path = tmp_path / "activity"
        activity_path.mkdir()
        _write_jsonl(
            activity_path,
            "2026-07-20",
            [
                {"timestamp": "2026-07-20T10:00:00", "summary": "a"},
            ],
        )

        conn = memory.get_db_connection()
        conn.close()
        with pytest.raises(sqlite3.Error):
            migration.run_migration(activity_path, conn)
