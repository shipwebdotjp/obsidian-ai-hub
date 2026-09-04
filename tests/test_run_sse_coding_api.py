"""API tests for coding reconnectable runs (plan step 4 + acceptance)."""

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from obsidian_ai_hub.coding import backend, store as coding_store
from obsidian_ai_hub.coding import service as coding_service
from obsidian_ai_hub.runs.coding_worker import execute_coding_run
from obsidian_ai_hub.web.app import create_app


def _client(api_token):
    return TestClient(create_app(host="127.0.0.1", port=0, token=api_token))


def _make_project_and_session(client, headers, tmp_path):
    repo = Path(tmp_path) / "repo"
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "README.md").write_text("# R\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)

    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    cur = conn.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status, project_path, created_at, updated_at)"
        " VALUES ('sse-c-proj', 'SSE C', 'personal', 'active', ?, datetime('now'), datetime('now'));",
        (str(repo),),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": pid, "backend": "codex", "title": "S"},
    )
    assert res.status_code == 200
    return res.json()["session_id"]


def _sse_payloads(text: str):
    out = []
    cur_id = None
    for line in text.splitlines():
        if line.startswith("id:"):
            cur_id = int(line[len("id:"):].strip())
        elif line.startswith("data:"):
            assert cur_id is not None
            out.append((cur_id, json.loads(line[len("data:"):].strip())))
    return out


def test_coding_start_idempotent_and_replay(api_token, tmp_path):
    client = _client(api_token)
    headers = {"Authorization": f"Bearer {api_token}"}
    sid = _make_project_and_session(client, headers, tmp_path)

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        json={"content": "do work"},
        headers={**headers, "Idempotency-Key": "ck-1"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]
    assert res.json()["run"]["status"] == "queued"

    res2 = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        json={"content": "do work"},
        headers={**headers, "Idempotency-Key": "ck-1"},
    )
    assert res2.status_code == 202
    assert res2.json()["run"]["run_id"] == run_id

    res3 = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        json={"content": "other"},
        headers={**headers, "Idempotency-Key": "ck-1"},
    )
    assert res3.status_code == 409

    res4 = client.post(
        f"/api/v1/coding/sessions/{sid}/runs", json={"content": "second"}, headers=headers
    )
    assert res4.status_code == 409

    # Execute with mocked orchestrator (no CLI) -> completed + done event.
    async def mock_generate_response(*args, **kwargs):
        return "完了しました。"

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ):
        asyncio.run(execute_coding_run(run_id))

    run = coding_store.get_run(run_id)
    assert run["status"] == "completed"

    sub = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert sub.status_code == 200
    payloads = _sse_payloads(sub.text)
    assert len(payloads) >= 2
    ids = [eid for eid, _ in payloads]
    assert ids == sorted(ids)
    assert payloads[-1][1].get("event") == "done"

    first = payloads[0][0]
    sub2 = client.get(
        f"/api/v1/coding/runs/{run_id}/events",
        headers={**headers, "Last-Event-ID": str(first)},
    )
    assert sub2.status_code == 200
    payloads2 = _sse_payloads(sub2.text)
    assert all(eid > first for eid, _ in payloads2)


def test_coding_worker_holds_lock_and_cancel_registry_during_cli(api_token, tmp_path):
    client = _client(api_token)
    headers = {"Authorization": f"Bearer {api_token}"}
    sid = _make_project_and_session(client, headers, tmp_path)
    run_id = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        json={"content": "lock check"},
        headers=headers,
    ).json()["run"]["run_id"]

    seen = {}

    async def mock_generate_response(*args, **kwargs):
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            return "完了しました。"
        return "解析\n<cli_request>\necho hi\n</cli_request>"

    def checking_execute(self, repo_path, prompt, external_session_id=None, cancel_event=None):
        # Repo lock and cancel registration must be held for the whole CLI call.
        seen["repo_busy"] = coding_service.is_repo_busy(repo_path)
        with coding_service._JOBS_GUARD:
            seen["job_registered"] = run_id in coding_service._RUNNING_JOBS
        return backend.CodingBackendResult(
            external_session_id="th_lock1", output="ok", exit_code=0
        )

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.CodexCliBackend.execute", checking_execute
    ):
        asyncio.run(execute_coding_run(run_id))

    assert seen.get("repo_busy") is True
    assert seen.get("job_registered") is True
    # Released after completion.
    assert coding_store.get_run(run_id)["status"] == "completed"
    with coding_service._JOBS_GUARD:
        assert run_id not in coding_service._RUNNING_JOBS


def test_coding_repo_lock_held_until_cli_done_and_cancel(api_token, tmp_path):
    client = _client(api_token)
    headers = {"Authorization": f"Bearer {api_token}"}
    sid = _make_project_and_session(client, headers, tmp_path)
    run_id = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        json={"content": "cli work"},
        headers=headers,
    ).json()["run"]["run_id"]

    # Claim to running so cancel path sees cancelling.
    claimed = coding_store.claim_queued_run("worker-1")
    assert claimed is not None

    # Cancel requests cancelling + signals worker job registry.
    import threading

    coding_service._RUNNING_JOBS[run_id] = (threading.Event(), "/tmp")
    try:
        res = client.post(f"/api/v1/coding/runs/{run_id}/cancel", headers=headers)
        assert res.status_code == 200
        assert res.json()["run"]["status"] == "cancelling"
        # Worker registry still holds the job until CLI completes (lock held).
        assert run_id in coding_service._RUNNING_JOBS
    finally:
        coding_service._RUNNING_JOBS.pop(run_id, None)

    # Terminal cancel is not_running but returns run.
    coding_store.transition_run_status(run_id, "cancelled", finished=True)
    res2 = client.post(f"/api/v1/coding/runs/{run_id}/cancel", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["status"] == "not_running"


def test_coding_delete_refused_while_active(api_token, tmp_path):
    client = _client(api_token)
    headers = {"Authorization": f"Bearer {api_token}"}
    sid = _make_project_and_session(client, headers, tmp_path)
    client.post(
        f"/api/v1/coding/sessions/{sid}/runs", json={"content": "active"}, headers=headers
    )
    res = client.delete(f"/api/v1/coding/sessions/{sid}", headers=headers)
    assert res.status_code == 409
