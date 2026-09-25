"""Per-session Coding Orchestrator provider/model selection.

Covers the store contract (override + config-default fallback + validation),
the Web API surface, and the end-to-end propagation into the orchestrator
built by the queued run worker.
"""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.coding import store as coding_store
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def test_project(tmp_path):
    git_repo = tmp_path / "orch_repo"
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
        " VALUES ('orch-repo', 'Orch Repo', 'personal', 'active', ?,"
        " datetime('now'), datetime('now'))",
        (str(git_repo),),
    )
    project_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"project_id": project_id, "repo_path": str(git_repo)}


def _defaults() -> tuple[str, str]:
    return (
        app_config.CODING_ORCHESTRATOR_PROVIDER,
        app_config.CODING_ORCHESTRATOR_MODEL,
    )


def test_store_session_orchestrator_override_and_fallback(tmp_path):
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    cursor = conn.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status,"
        " project_path, created_at, updated_at)"
        " VALUES ('store-orch', 'Store Orch', 'personal', 'active', ?,"
        " datetime('now'), datetime('now'))",
        (str(tmp_path),),
    )
    project_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Unset override -> config defaults.
    default_session = coding_store.create_session(
        project_id=project_id, backend="opencode", repo_path=str(tmp_path)
    )
    assert default_session["orchestrator_provider"] is None
    assert default_session["orchestrator_model"] is None
    assert coding_store.get_effective_session_orchestrator(default_session) == _defaults()

    # Explicit override persists and resolves.
    override = coding_store.create_session(
        project_id=project_id,
        backend="opencode",
        repo_path=str(tmp_path),
        orchestrator_provider="opencode_go",
        orchestrator_model="glm-5.2",
    )
    assert override["orchestrator_provider"] == "opencode_go"
    assert override["orchestrator_model"] == "glm-5.2"
    assert coding_store.get_effective_session_orchestrator(override) == (
        "opencode_go",
        "glm-5.2",
    )

    # Update replaces the override.
    updated = coding_store.update_session_orchestrator(
        override["session_id"], "openai", "gpt-5.6-terra"
    )
    assert coding_store.get_effective_session_orchestrator(updated) == (
        "openai",
        "gpt-5.6-terra",
    )

    # Clearing both fields falls back to config defaults again.
    cleared = coding_store.update_session_orchestrator(override["session_id"], None, None)
    assert cleared["orchestrator_provider"] is None
    assert cleared["orchestrator_model"] is None
    assert coding_store.get_effective_session_orchestrator(cleared) == _defaults()

    # Unknown provider / missing model / partial pair are rejected.
    with pytest.raises(ValueError):
        coding_store.update_session_orchestrator(override["session_id"], "bogus", "x")
    with pytest.raises(ValueError):
        coding_store.update_session_orchestrator(override["session_id"], "openai", "")
    with pytest.raises(ValueError):
        coding_store.create_session(
            project_id=project_id,
            backend="opencode",
            repo_path=str(tmp_path),
            orchestrator_provider="openai",
        )

    # Missing session surfaces as FileNotFoundError.
    with pytest.raises(FileNotFoundError):
        coding_store.update_session_orchestrator("cses_missing", "openai", "x")


def test_orchestrator_api(api_token, test_project):
    client = TestClient(create_app(token=api_token))
    headers = {"Authorization": f"Bearer {api_token}"}

    cfg = client.get("/api/v1/coding/config", headers=headers).json()
    assert cfg["orchestrator_provider"] == app_config.CODING_ORCHESTRATOR_PROVIDER
    assert cfg["orchestrator_model"] == app_config.CODING_ORCHESTRATOR_MODEL
    assert "opencode_go" in cfg["available_orchestrator_providers"]

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "opencode",
            "title": "Orch",
        },
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]

    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    assert detail["effective_orchestrator_provider"] == app_config.CODING_ORCHESTRATOR_PROVIDER
    assert detail["effective_orchestrator_model"] == app_config.CODING_ORCHESTRATOR_MODEL
    assert "opencode_go" in detail["available_orchestrator_providers"]

    chg = client.put(
        f"/api/v1/coding/sessions/{sid}/orchestrator",
        headers=headers,
        json={"orchestrator_provider": "opencode_go", "orchestrator_model": "glm-5.2"},
    )
    assert chg.status_code == 200
    body = chg.json()
    assert body["session"]["orchestrator_provider"] == "opencode_go"
    assert body["session"]["orchestrator_model"] == "glm-5.2"
    assert body["effective_orchestrator_provider"] == "opencode_go"
    assert body["effective_orchestrator_model"] == "glm-5.2"

    bad = client.put(
        f"/api/v1/coding/sessions/{sid}/orchestrator",
        headers=headers,
        json={"orchestrator_provider": "bogus", "orchestrator_model": "x"},
    )
    assert bad.status_code == 400

    cleared = client.put(
        f"/api/v1/coding/sessions/{sid}/orchestrator",
        headers=headers,
        json={},
    )
    assert cleared.status_code == 200
    assert cleared.json()["session"]["orchestrator_provider"] is None
    assert (
        cleared.json()["effective_orchestrator_provider"]
        == app_config.CODING_ORCHESTRATOR_PROVIDER
    )


def _run_worker_capturing_orchestrator(client, headers, project, session_payload):
    import obsidian_ai_hub.coding.orchestrator as orch_module
    from obsidian_ai_hub.runs.coding_worker import execute_coding_run

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": project["project_id"],
            "backend": "opencode",
            "title": "Capture",
            **session_payload,
        },
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]

    run_res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "go"},
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["run"]["run_id"]

    captured: dict = {}
    real_cls = orch_module.CodingOrchestrator

    class CapturingOrchestrator(real_cls):
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            super().__init__(*args, **kwargs)

    async def mock_gen(*args, **kwargs):
        return "<final_report>done</final_report>"

    with (
        patch.object(orch_module, "CodingOrchestrator", CapturingOrchestrator),
        patch.object(real_cls, "generate_response", side_effect=mock_gen),
    ):
        asyncio.run(execute_coding_run(run_id))

    return captured


def test_worker_uses_session_orchestrator_override(api_token, test_project):
    client = TestClient(create_app(token=api_token))
    headers = {"Authorization": f"Bearer {api_token}"}

    captured = _run_worker_capturing_orchestrator(
        client,
        headers,
        test_project,
        {"orchestrator_provider": "opencode_go", "orchestrator_model": "glm-5.2"},
    )
    assert captured.get("provider") == "opencode_go"
    assert captured.get("model") == "glm-5.2"


def test_worker_uses_config_default_without_override(api_token, test_project):
    client = TestClient(create_app(token=api_token))
    headers = {"Authorization": f"Bearer {api_token}"}

    captured = _run_worker_capturing_orchestrator(client, headers, test_project, {})
    assert captured.get("provider") == app_config.CODING_ORCHESTRATOR_PROVIDER
    assert captured.get("model") == app_config.CODING_ORCHESTRATOR_MODEL
