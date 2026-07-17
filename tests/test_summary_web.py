# ruff: noqa: E402
import sys
from unittest.mock import MagicMock

mock_modules = {
    "EventKit": MagicMock(),
    "AppKit": MagicMock(),
    "objc": MagicMock(),
    "Foundation": MagicMock(),
    "ApplicationServices": MagicMock(),
    "atomacos": MagicMock(),
    "Quartz": MagicMock(),
    "Vision": MagicMock(),
    "Cocoa": MagicMock(),
}
for name, m in mock_modules.items():
    sys.modules[name] = m

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub import memory
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.utils import config
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def clean_summary_env(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault"
    vault_path.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "VAULT_PATH", vault_path)

    activity_dir = vault_path / "activity"
    activity_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "ACTIVITY_PATH", activity_dir)

    db_path = tmp_path / "memory.sqlite3"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_path)

    return vault_path


@pytest.fixture
def loopback_client(clean_summary_env):
    app = create_app(host="127.0.0.1", port=0, token="")
    return TestClient(app)


@pytest.fixture
def token_client(clean_summary_env):
    app = create_app(host="0.0.0.0", port=0, token="test-token")
    return TestClient(app)


def _seed_day(period_key: str, summary: str, topics: list[str] | None = None):
    summary_store.upsert_summary({
        "period_type": "day",
        "period_key": period_key,
        "period_start": period_key,
        "period_end": period_key,
        "generated_at": f"{period_key}T22:00:00",
        "summary": summary,
        "keywords": [],
        "mood": "good",
        "sleep_raw": "7h",
        "sleep_hours": 7.0,
        "topics": topics or ["その他"],
        "projects": ["Project A"],
        "people": [{"name": "Alice", "note": "met"}],
        "items": [
            {"kind": "highlights", "body": f"Highlight for {period_key}", "display_order": 0},
            {"kind": "activities", "body": f"Activity for {period_key}", "display_order": 0},
        ],
    })


def _seed_week(period_key: str, summary: str):
    summary_store.upsert_summary({
        "period_type": "week",
        "period_key": period_key,
        "period_start": "2026-07-13",
        "period_end": "2026-07-19",
        "generated_at": "2026-07-19T22:00:00",
        "summary": summary,
        "keywords": [],
        "mood": None,
        "sleep_raw": None,
        "sleep_hours": None,
        "topics": ["LLM・AI活用"],
        "projects": ["Project B"],
        "people": [{"name": "Bob", "note": ""}],
        "items": [
            {"kind": "progress", "body": f"Progress for {period_key}", "display_order": 0},
        ],
    })


def test_list_summaries(loopback_client, clean_summary_env):
    _seed_day("2026-07-13", "Day 1", topics=["LLM・AI活用"])
    _seed_day("2026-07-14", "Day 2", topics=["健康・医療"])
    _seed_week("2026-W29", "Week 29")

    res = loopback_client.get("/api/v1/summaries")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3


def test_list_summaries_filter_period_type(loopback_client, clean_summary_env):
    _seed_day("2026-07-13", "Day 1")
    _seed_week("2026-W29", "Week 29")

    res = loopback_client.get("/api/v1/summaries?period_type=day")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["period_type"] == "day"


def test_list_summaries_filter_topic(loopback_client, clean_summary_env):
    _seed_day("2026-07-13", "Day 1", topics=["LLM・AI活用"])
    _seed_day("2026-07-14", "Day 2", topics=["健康・医療"])

    res = loopback_client.get("/api/v1/summaries?topic=LLM・AI活用")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["summary"] == "Day 1"


def test_list_summaries_filter_project(loopback_client, clean_summary_env):
    _seed_day("2026-07-13", "Day 1")
    _seed_week("2026-W29", "Week 29")

    res = loopback_client.get("/api/v1/summaries?project=Project%20B")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["period_type"] == "week"


def test_list_summaries_filter_person(loopback_client, clean_summary_env):
    _seed_day("2026-07-13", "Day 1")
    _seed_week("2026-W29", "Week 29")

    res = loopback_client.get("/api/v1/summaries?person=Alice")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["summary"] == "Day 1"


def test_list_summaries_invalid_period_type(loopback_client, clean_summary_env):
    res = loopback_client.get("/api/v1/summaries?period_type=year")
    assert res.status_code == 400


def test_get_summary_detail(loopback_client, clean_summary_env):
    _seed_day("2026-07-13", "Day 1")

    # Get summary_id from DB
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT summary_id FROM summaries WHERE period_key = ?", ("2026-07-13",))
        summary_id = cursor.fetchone()["summary_id"]
    finally:
        conn.close()

    res = loopback_client.get(f"/api/v1/summaries/{summary_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["summary_id"] == summary_id
    assert data["summary"] == "Day 1"
    assert data["mood"] == "good"
    assert len(data["items"]) == 2
    assert data["people"][0]["name"] == "Alice"


def test_get_summary_not_found(loopback_client, clean_summary_env):
    res = loopback_client.get("/api/v1/summaries/nonexistent")
    assert res.status_code == 404


def test_summary_options(loopback_client, clean_summary_env):
    _seed_day("2026-07-13", "Day 1", topics=["LLM・AI活用"])

    res = loopback_client.get("/api/v1/summary-options")
    assert res.status_code == 200
    data = res.json()
    assert "LLM・AI活用" in data["topics"]
    assert "Project A" in data["projects"]
    assert "Alice" in data["people"]


def test_token_required_for_non_loopback(token_client, clean_summary_env):
    res = token_client.get("/api/v1/summaries")
    assert res.status_code == 401

    res = token_client.get("/api/v1/summaries", headers={"Authorization": "Bearer test-token"})
    assert res.status_code == 200


def test_summary_detail_has_no_write_methods(loopback_client, clean_summary_env):
    _seed_day("2026-07-13", "Day 1")
    res = loopback_client.post("/api/v1/summaries")
    assert res.status_code == 405
