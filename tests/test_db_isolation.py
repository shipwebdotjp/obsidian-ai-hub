from __future__ import annotations

from pathlib import Path

import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub.research import db as research_db
from obsidian_ai_hub.utils import config


def test_research_db_uses_the_test_sqlite_file(test_memory_db_path: Path):
    research_db.create_theme(theme="テスト専用テーマ")

    with memory.get_db_connection() as conn:
        database_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])

    assert database_path == test_memory_db_path
    assert research_db.list_themes()[0]["theme"] == "テスト専用テーマ"


def test_test_mode_refuses_the_recorded_production_db(tmp_path: Path, monkeypatch):
    protected_path = tmp_path / "production.sqlite3"
    monkeypatch.setenv("OBSIDIAN_AI_HUB_TEST_PRODUCTION_DB_PATH", str(protected_path))
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", protected_path)

    with pytest.raises(RuntimeError, match="production memory database"):
        memory.get_db_connection()

    assert not protected_path.exists()
