from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.web.app import create_app


def _count_hitl_runs(conn) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM hitl_runs")
    return cursor.fetchone()[0]


def test_web_manual_research_paths_do_not_create_hitl_runs(test_memory_db_path):
    """Web research endpoints (run, rerun) must not create HITL runs."""
    conn = get_db_connection()
    try:
        assert _count_hitl_runs(conn) == 0

        app = create_app()
        client = TestClient(app)

        # Web POST /api/v1/research-themes/run — mock the service layer
        theme_mock = {
            "theme_id": "manual_web_1",
            "theme": "テストテーマWeb",
            "status": "candidate",
            "normalized_key": "testtheme",
            "direction": "",
            "kind": "explore",
            "why_now": "",
            "confidence": 0.8,
            "related_theme_ids": [],
            "duplicate_of_theme_id": None,
            "duplicate_reason": None,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        job_mock = {"job_id": "job_1", "status": "pending", "theme_id": "manual_web_1"}
        with patch("obsidian_ai_hub.web.service.run_research_theme") as mock_svc:
            mock_svc.return_value = (theme_mock, job_mock)
            res = client.post(
                "/api/v1/research-themes/run",
                json={"theme": "Web研究テーマ", "mode": "auto"},
            )
            assert res.status_code == 202
        assert _count_hitl_runs(conn) == 0, "POST /run must not create HITL run"

        # Web POST /api/v1/research-themes/{id}/rerun
        from obsidian_ai_hub.research.db import create_theme

        theme_rec = create_theme(
            theme="テーマRerun",
            direction="方向",
            kind="explore",
            status="approved",
            conn=conn,
        )
        assert _count_hitl_runs(conn) == 0

        with patch("obsidian_ai_hub.web.service.rerun_research_theme") as mock_rerun:
            mock_rerun.return_value = {"job_id": "job_2", "status": "pending", "theme_id": theme_rec["theme_id"]}
            res = client.post(f"/api/v1/research-themes/{theme_rec['theme_id']}/rerun")
            assert res.status_code == 200
        assert _count_hitl_runs(conn) == 0, "POST /rerun must not create HITL run"

    finally:
        conn.close()
