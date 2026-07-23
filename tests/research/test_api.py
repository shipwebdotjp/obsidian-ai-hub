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
    from obsidian_ai_hub.research import db as research_themes

    return research_themes.create_theme(
        theme="APIテストテーマ",
        direction="API方向",
        kind="deep",
        why_now="理由",
        confidence=0.85,
    )


def _create_test_job(theme_id: str):
    from obsidian_ai_hub.research import db as research_themes

    job = research_themes.create_job(theme_id)
    research_themes.update_job(
        job["job_id"],
        status="succeeded",
        generated_title="APIテスト",
        mode="internal",
        markdown="# 結果",
    )
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
    from obsidian_ai_hub.research import db as research_themes

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


def test_rerun_research_theme(client):
    t = _create_test_theme()

    with (
        patch(
            "obsidian_ai_hub.research.runner.collect_research_context", return_value=""
        ),
        patch(
            "obsidian_ai_hub.research.runner.route_research_topic",
            return_value="internal",
        ),
        patch(
            "obsidian_ai_hub.research.runner.llm_client.generate_llm_response",
            return_value="title",
        ),
        patch(
            "obsidian_ai_hub.research.runner.conduct_research", return_value="report"
        ),
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


def test_run_research_theme_validation_error(client):
    # Empty theme
    resp = client.post(
        "/api/v1/research-themes/run", json={"theme": "", "mode": "auto"}
    )
    assert resp.status_code == 400

    # Blank theme
    resp = client.post(
        "/api/v1/research-themes/run", json={"theme": "   ", "mode": "auto"}
    )
    assert resp.status_code == 400

    # Invalid mode
    resp = client.post(
        "/api/v1/research-themes/run", json={"theme": "テスト", "mode": "invalid"}
    )
    assert resp.status_code == 422


def test_run_research_theme_success(client):
    with patch("obsidian_ai_hub.research.runner.submit_research_job_bg") as mock_submit:
        resp = client.post(
            "/api/v1/research-themes/run",
            json={"theme": "APIテスト即時テーマ", "mode": "deep"},
        )

    assert resp.status_code == 202
    data = resp.json()
    assert data["theme"]["theme"] == "APIテスト即時テーマ"
    assert data["theme"]["status"] == "candidate"
    assert data["job"]["status"] == "pending"
    assert data["theme"]["latest_job"]["job_id"] == data["job"]["job_id"]

    mock_submit.assert_called_once_with(
        theme_id=data["theme"]["theme_id"], job_id=data["job"]["job_id"], mode="deep"
    )


def test_cleanup_stale_jobs_on_startup():
    from obsidian_ai_hub.research import db as research_db

    theme = research_db.create_theme(theme="StaleJobTheme", status="candidate")
    job = research_db.create_job(theme["theme_id"])
    research_db.update_job(job["job_id"], status="running")

    # Before startup cleanup
    stale_job = research_db.latest_job(theme["theme_id"])
    assert stale_job["status"] == "running"

    # Trigger startup cleanup by instantiating the app with TestClient context manager
    app = create_app(host="127.0.0.1", port=8765, token="test-token")
    with TestClient(app):
        pass

    cleaned_job = research_db.latest_job(theme["theme_id"])
    assert cleaned_job["status"] == "failed"
    assert cleaned_job["error"] == "サーバー再起動により中断"

    # Ensure theme is still candidate
    t_obj = research_db.get_theme(theme["theme_id"])
    assert t_obj["status"] == "candidate"
