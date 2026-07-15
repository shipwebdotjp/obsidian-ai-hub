from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def client():
    app = create_app(host="127.0.0.1", port=8765, token="test-token")
    return TestClient(app)


def _create_test_theme():
    from obsidian_ai_hub import research_themes
    return research_themes.create_theme(
        theme="APIテストテーマ",
        direction="API方向",
        kind="deep",
        why_now="理由",
        confidence=0.85,
    )


def _create_test_job(theme_id: str):
    from obsidian_ai_hub import research_themes
    job = research_themes.create_job(theme_id)
    research_themes.update_job(job["job_id"], status="succeeded", generated_title="APIテスト", mode="internal", markdown="# 結果")
    return job


def test_list_research_themes(client):
    _create_test_theme()
    resp = client.get("/api/v1/research-themes")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] >= 1


def test_list_research_themes_with_status_filter(client):
    t = _create_test_theme()
    from obsidian_ai_hub import research_themes
    research_themes.set_status(t["theme_id"], "approved", reviewed_by="test")

    resp = client.get("/api/v1/research-themes?status=approved")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(i["status"] == "approved" for i in items)


def test_list_research_themes_with_search(client):
    _create_test_theme()
    resp = client.get("/api/v1/research-themes?q=APIテストテーマ")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1


def test_get_research_theme(client):
    t = _create_test_theme()
    _create_test_job(t["theme_id"])

    resp = client.get(f"/api/v1/research-themes/{t['theme_id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["theme"] == "APIテストテーマ"
    assert data["latest_job"] is not None


def test_get_research_theme_not_found(client):
    resp = client.get("/api/v1/research-themes/nonexistent")
    assert resp.status_code == 404


def test_review_research_theme_approve(client):
    t = _create_test_theme()
    _create_test_job(t["theme_id"])

    with patch("obsidian_ai_hub.research_agent.save_research_to_vault", return_value=None):
        resp = client.post(f"/api/v1/research-themes/{t['theme_id']}/review", json={"action": "approve"})

    assert resp.status_code == 200
    assert resp.json()["theme"]["status"] == "approved"


def test_review_research_theme_reject(client):
    t = _create_test_theme()
    resp = client.post(f"/api/v1/research-themes/{t['theme_id']}/review", json={"action": "reject"})
    assert resp.status_code == 200
    assert resp.json()["theme"]["status"] == "rejected"


def test_review_research_theme_not_found(client):
    resp = client.post("/api/v1/research-themes/nonexistent/review", json={"action": "approve"})
    assert resp.status_code == 404


def test_rerun_research_theme(client):
    t = _create_test_theme()

    with (
        patch("obsidian_ai_hub.research_agent.collect_research_context", return_value=""),
        patch("obsidian_ai_hub.research_agent.route_research_topic", return_value="internal"),
        patch("obsidian_ai_hub.research_agent.llm_client.generate_llm_response", return_value="title"),
        patch("obsidian_ai_hub.research_agent.conduct_research", return_value="report"),
    ):
        resp = client.post(f"/api/v1/research-themes/{t['theme_id']}/rerun")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "succeeded"


def test_rerun_research_theme_not_found(client):
    resp = client.post("/api/v1/research-themes/nonexistent/rerun")
    assert resp.status_code == 404


def test_invalid_status_filter(client):
    resp = client.get("/api/v1/research-themes?status=invalid")
    assert resp.status_code == 400


def test_loopback_auth_bypass(client):
    app = create_app(host="127.0.0.1", port=8765, token="")
    bypass_client = TestClient(app)
    resp = bypass_client.get("/api/v1/research-themes")
    assert resp.status_code == 200
