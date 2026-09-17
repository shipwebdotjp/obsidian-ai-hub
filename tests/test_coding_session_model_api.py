"""Acceptance tests: model change API during an active run + frozen send path.

- PUT /coding/sessions/{id}/model succeeds for allowlisted models even
  while a run is active, and rejects unlisted / free-form models (400).
- The in-flight run keeps the model frozen at run start
  (``execute_turn`` keeps receiving the old model), while the next run
  receives the changed model. The frozen model reaches ACP via
  ``session/set_model``.
"""

import asyncio
import subprocess

from fastapi.testclient import TestClient
from unittest.mock import patch

import pytest

from obsidian_ai_hub.coding import acp, store
from obsidian_ai_hub.runs.coding_worker import execute_coding_run
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def model_allowlist(monkeypatch):
    from obsidian_ai_hub.utils import config as app_config

    monkeypatch.setenv("CODING_OPENCODE_MODELS", "model-alpha,model-beta")
    monkeypatch.setattr(app_config, "CODING_OPENCODE_MODEL", "model-alpha", raising=False)


@pytest.fixture
def test_project(tmp_path):
    git_repo = tmp_path / "model_repo"
    git_repo.mkdir()
    subprocess.run(["git", "init"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=git_repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=git_repo, check=True)
    (git_repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=git_repo, check=True)

    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    cursor = conn.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status,"
        " project_path, created_at, updated_at)"
        " VALUES ('model-repo', 'Model Repo', 'personal', 'active', ?,"
        " datetime('now'), datetime('now'))",
        (str(git_repo),),
    )
    project_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"project_id": project_id, "repo_path": str(git_repo)}


def _diag(repo_path, ses):
    return {
        "cwd": repo_path,
        "requested_session_id": ses,
        "returned_session_id": ses,
        "tool_call_count": 0,
        "tool_failure_count": 0,
        "structured_error": None,
        "auto_rejected_permission": False,
        "exit_code": 0,
        "model": "test",
        "variant": "なし",
        "session_recreated": False,
    }


def test_create_session_uses_config_default_model(
    api_token, test_project, model_allowlist
):
    """Creating without opencode_model applies the config default (no user pick)."""
    client = TestClient(create_app(token="test-token"))
    headers = {"Authorization": "Bearer test-token"}

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "opencode",
            "title": "Default",
        },
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]

    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    assert detail["session"]["opencode_model"] == "model-alpha"
    assert detail["effective_model"] == "model-alpha"
    assert detail["available_models"] == ["model-alpha", "model-beta"]


def test_model_change_api_during_active_run(api_token, test_project, model_allowlist):
    client = TestClient(create_app(token="test-token"))
    headers = {"Authorization": "Bearer test-token"}

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "opencode",
            "title": "M",
            "opencode_model": "model-alpha",
        },
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]

    run = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "do work"},
    )
    assert run.status_code == 202  # run is now active (queued)

    # Allowlisted change succeeds DURING the active run and persists.
    chg = client.put(
        f"/api/v1/coding/sessions/{sid}/model",
        headers=headers,
        json={"opencode_model": "model-beta"},
    )
    assert chg.status_code == 200
    body = chg.json()
    assert body["session"]["opencode_model"] == "model-beta"
    assert body["effective_model"] == "model-beta"

    # Unlisted / free-form model is rejected even with an active run.
    bad = client.put(
        f"/api/v1/coding/sessions/{sid}/model",
        headers=headers,
        json={"opencode_model": "evil-model"},
    )
    assert bad.status_code == 400


def test_inflight_run_keeps_frozen_model_next_run_uses_new(
    api_token, test_project, model_allowlist
):
    client = TestClient(create_app(token="test-token"))
    headers = {"Authorization": "Bearer test-token"}

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "opencode",
            "title": "M",
            "opencode_model": "model-alpha",
        },
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]

    async def mock_gen(*args, **kwargs):
        history = kwargs.get("history", [])
        workers = [h for h in history if h.get("role") == "worker"]
        if len(workers) < 2:
            return "work\n<cli_request>\ncli\n</cli_request>"
        return "<final_report>final</final_report>"

    r1 = acp.AcpExecutionResult(
        acp_session_id="ses_m1", output="o1", exit_code=0,
        diagnostics=_diag(test_project["repo_path"], "ses_m1"),
    )
    r2 = acp.AcpExecutionResult(
        acp_session_id="ses_m1", output="o2", exit_code=0,
        diagnostics=_diag(test_project["repo_path"], "ses_m1"),
    )

    seen_models: list = []

    def fake_execute_turn(**kwargs):
        seen_models.append(kwargs.get("model"))
        if len(seen_models) == 1:
            # Simulate the user changing the model mid-run.
            store.update_session_model(sid, "model-beta")
            return r1
        return r2

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "multi"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
            side_effect=mock_gen,
        ),
        patch(
            "obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn",
            side_effect=fake_execute_turn,
        ),
    ):
        asyncio.run(execute_coding_run(run_id))

    # Both worker turns of the in-flight run used the frozen (pre-change) model.
    assert seen_models == ["model-alpha", "model-alpha"]

    # The next message's run resolves the changed model through the real path.
    res2 = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "next"},
    )
    assert res2.status_code == 202
    run_id2 = res2.json()["run"]["run_id"]

    seen2: list = []
    r3 = acp.AcpExecutionResult(
        acp_session_id="ses_m1", output="o3", exit_code=0,
        diagnostics=_diag(test_project["repo_path"], "ses_m1"),
    )

    def fake_execute_turn2(**kwargs):
        seen2.append(kwargs.get("model"))
        return r3

    final_calls = {"n": 0}

    async def mock_gen_final(*args, **kwargs):
        final_calls["n"] += 1
        if final_calls["n"] == 1:
            return "work\n<cli_request>\ncli\n</cli_request>"
        return "<final_report>done</final_report>"

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
            side_effect=mock_gen_final,
        ),
        patch(
            "obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn",
            side_effect=fake_execute_turn2,
        ),
    ):
        asyncio.run(execute_coding_run(run_id2))

    assert seen2 and all(m == "model-beta" for m in seen2)


def test_frozen_model_reaches_acp_set_model(model_allowlist):
    profile = acp.AcpLaunchProfile.get_profile("opencode")
    backend = acp.AcpClientBackend(profile)

    captured = {}

    class _Conn:
        def request(self, method, params, timeout=None):
            captured["method"] = method
            captured["params"] = params
            return {}

    sent = backend._apply_session_model(_Conn(), "sess", model="model-beta")
    assert sent == "model-beta"
    assert captured["method"] == "session/set_model"
    assert captured["params"] == {"sessionId": "sess", "modelId": "model-beta"}
