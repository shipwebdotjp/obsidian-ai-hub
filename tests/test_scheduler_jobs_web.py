# ruff: noqa: E402
import sys
from unittest.mock import MagicMock

import pytest
import yaml
from datetime import datetime
from fastapi.testclient import TestClient

from obsidian_ai_hub.utils import config
from obsidian_ai_hub.scheduler_jobs import recurring


@pytest.fixture(autouse=True)
def _mock_macos_modules(monkeypatch):
    # Mock macOS-specific modules before obsidian_ai_hub web imports resolve.
    # monkeypatch reverts sys.modules afterwards so unrelated tests are unaffected.
    for name in (
        "EventKit",
        "AppKit",
        "objc",
        "Foundation",
        "ApplicationServices",
        "atomacos",
        "Quartz",
        "Vision",
        "Cocoa",
    ):
        monkeypatch.setitem(sys.modules, name, MagicMock())


@pytest.fixture
def clean_job_env(tmp_path, monkeypatch):
    # Set up isolation for jobs & state files
    test_state_file = tmp_path / "last_run.json"
    monkeypatch.setattr(recurring, "STATE_FILE", test_state_file)
    monkeypatch.setattr(config, "JOB_RUN_STATE_PATH", test_state_file)

    test_job_file = tmp_path / "jobs.test.yml"
    monkeypatch.setattr(recurring, "TEST_JOB_FILE", test_job_file)
    monkeypatch.setattr(recurring, "LOCAL_JOB_FILE", test_job_file)
    monkeypatch.setattr(recurring, "DEFAULT_JOB_FILE", test_job_file)

    # Set up config file locks
    monkeypatch.setattr(recurring, "LOCK_FILE", tmp_path / ".job-config.lock")
    monkeypatch.setattr(recurring, "RUNNER_LOCK_FILE", tmp_path / ".job-runner.lock")

    monkeypatch.setattr(config, "IS_TEST_ENV", True)

    return test_job_file, test_state_file


@pytest.fixture
def web_client(clean_job_env, api_token, api_auth_headers):
    from obsidian_ai_hub.web.app import create_app
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


def test_get_recurring_jobs_empty(clean_job_env, web_client):
    job_file, _ = clean_job_env
    # Initialize task file
    recurring.atomic_write_yaml(job_file, [])

    res = web_client.get("/api/v1/scheduler-jobs/recurring-jobs")
    assert res.status_code == 200
    body = res.json()
    assert body["jobs"] == []
    assert body["filepath"] == str(job_file)
    assert len(body["revision"]) == 64  # SHA-256 hash length


def test_get_recurring_jobs_with_preset_and_custom(clean_job_env, web_client):
    job_file, _ = clean_job_env
    initial_jobs = [
        {
            "id": "job_preset",
            "enabled": True,
            "schedule": {"type": "minutely", "second": 0},
            "command": "uv --directory /some/base run -m obsidian_ai_hub --merge-inbox"
        },
        {
            "id": "job_custom",
            "enabled": False,
            "schedule": {"type": "daily", "hour": 12, "minute": 30},
            "command": "echo 'arbitrary command'"
        }
    ]
    recurring.atomic_write_yaml(job_file, initial_jobs)

    res = web_client.get("/api/v1/scheduler-jobs/recurring-jobs")
    assert res.status_code == 200
    body = res.json()
    assert len(body["jobs"]) == 2

    preset_job = next(t for t in body["jobs"] if t["id"] == "job_preset")
    assert preset_job["is_preset"] is True
    assert preset_job["preset_flag"] == "--merge-inbox"
    assert preset_job["preset_name"] == "Inbox merge"
    assert preset_job["next_run"] is not None

    custom_job = next(t for t in body["jobs"] if t["id"] == "job_custom")
    assert custom_job["is_preset"] is False
    assert custom_job["preset_flag"] is None
    assert custom_job["next_run"] is not None


def test_recurring_jobs_requires_token(clean_job_env, api_token):
    from obsidian_ai_hub.web.app import create_app
    # Even a loopback client without a token is rejected.
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    client = TestClient(app)

    res = client.get("/api/v1/scheduler-jobs/recurring-jobs")
    assert res.status_code == 401
    assert res.json()["detail"] == "invalid or missing bearer token"

    # A LAN client with a valid token is accepted.
    lan_client = TestClient(
        app,
        client=("192.168.1.5", 50000),
        headers={"Authorization": f"Bearer {api_token}"},
    )
    res = lan_client.get("/api/v1/scheduler-jobs/recurring-jobs")
    assert res.status_code == 200


def test_update_recurring_jobs_success_and_arming(clean_job_env, web_client):
    job_file, state_file = clean_job_env

    # 1. Write initial state
    initial_jobs = [
        {
            "id": "job_unchanged",
            "enabled": True,
            "schedule": {"type": "hourly", "minute": 0},
            "command": "uv --directory /app run -m obsidian_ai_hub --backup"
        },
        {
            "id": "job_to_change",
            "enabled": True,
            "schedule": {"type": "hourly", "minute": 30},
            "command": "echo 'original command'"
        }
    ]
    recurring.atomic_write_yaml(job_file, initial_jobs)

    # Set historical last run times
    old_now = datetime(2026, 1, 1, 10, 0, 0)
    recurring.save_state({
        "job_unchanged": old_now,
        "job_to_change": old_now
    })

    # Fetch initial revision
    get_res = web_client.get("/api/v1/scheduler-jobs/recurring-jobs")
    rev = get_res.json()["revision"]

    # 2. Update via PUT
    updated_jobs = [
        {
            "id": "job_unchanged",
            "enabled": True,
            "schedule": {"type": "hourly", "minute": 0},
            "command": "uv --directory /app run -m obsidian_ai_hub --backup"
        },
        {
            "id": "job_to_change",
            "enabled": True,
            "schedule": {"type": "hourly", "minute": 45}, # Schedule changed!
            "command": "echo 'original command'"
        },
        {
            "id": "job_new",
            "enabled": True,
            "schedule": {"type": "minutely", "second": 10}, # New task!
            "command": "echo 'new command'"
        }
    ]

    put_res = web_client.put("/api/v1/scheduler-jobs/recurring-jobs", json={
        "revision": rev,
        "jobs": updated_jobs
    })
    assert put_res.status_code == 200
    assert put_res.json()["success"] is True
    new_rev = put_res.json()["revision"]
    assert new_rev != rev

    # Verify atomic file update
    with open(job_file, "r") as f:
        saved_jobs = yaml.safe_load(f)
    assert len(saved_jobs) == 3

    # Verify arming in state
    state = recurring.load_state()
    # job_unchanged should remain old_now (no arming!)
    assert state["job_unchanged"] == old_now
    # job_to_change and job_new should be armed with today's datetime (now)
    assert state["job_to_change"] > old_now
    assert state["job_new"] > old_now


def test_update_recurring_jobs_conflict(clean_job_env, web_client):
    job_file, _ = clean_job_env
    recurring.atomic_write_yaml(job_file, [])

    # Put with wrong revision
    res = web_client.put("/api/v1/scheduler-jobs/recurring-jobs", json={
        "revision": "mismatched-revision-hash",
        "jobs": []
    })
    assert res.status_code == 409
    assert "Conflict" in res.json()["detail"]


def test_update_recurring_jobs_validation_errors(clean_job_env, web_client):
    job_file, _ = clean_job_env
    recurring.atomic_write_yaml(job_file, [])

    get_res = web_client.get("/api/v1/scheduler-jobs/recurring-jobs")
    rev = get_res.json()["revision"]

    # 1. Duplicate IDs
    invalid_jobs = [
        {"id": "dup", "schedule": {"type": "minutely"}, "command": "echo 1"},
        {"id": "dup", "schedule": {"type": "minutely"}, "command": "echo 2"}
    ]
    res = web_client.put("/api/v1/scheduler-jobs/recurring-jobs", json={"revision": rev, "jobs": invalid_jobs})
    assert res.status_code == 422

    # 2. Invalid cron
    invalid_jobs = [
        {"id": "t1", "schedule": {"type": "minutely", "second": 100}, "command": "echo 1"}
    ]
    res = web_client.put("/api/v1/scheduler-jobs/recurring-jobs", json={"revision": rev, "jobs": invalid_jobs})
    assert res.status_code == 422

    # 3. Unrelated fields
    invalid_jobs = [
        {"id": "t2", "schedule": {"type": "minutely", "day": 10}, "command": "echo 1"}
    ]
    res = web_client.put("/api/v1/scheduler-jobs/recurring-jobs", json={"revision": rev, "jobs": invalid_jobs})
    assert res.status_code == 422

    # 4. Command syntax (unclosed quote)
    invalid_jobs = [
        {"id": "t3", "schedule": {"type": "minutely"}, "command": "echo 'unclosed quote"}
    ]
    res = web_client.put("/api/v1/scheduler-jobs/recurring-jobs", json={"revision": rev, "jobs": invalid_jobs})
    assert res.status_code == 422


def test_preview_command_success(web_client):
    res = web_client.post("/api/v1/scheduler-jobs/preview", json={
        "command": "cd /app/projects && uv run python -m test_module --args"
    })
    assert res.status_code == 200
    body = res.json()
    assert len(body["segments"]) == 1
    assert body["segments"][0]["cwd"] == "/app/projects"
    assert body["segments"][0]["args"] == ["uv", "run", "python", "-m", "test_module", "--args"]
    assert body["is_preset"] is False


def test_preview_command_preset(web_client):
    res = web_client.post("/api/v1/scheduler-jobs/preview", json={
        "command": "uv --directory /app run -m obsidian_ai_hub --merge-inbox"
    })
    assert res.status_code == 200
    body = res.json()
    assert body["is_preset"] is True
    assert body["preset_flag"] == "--merge-inbox"
    assert body["preset_name"] == "Inbox merge"


def test_preview_command_error(web_client):
    res = web_client.post("/api/v1/scheduler-jobs/preview", json={
        "command": "echo \"unclosed quote"
    })
    assert res.status_code == 422


def test_legacy_scheduler_routes_gone(web_client):
    assert web_client.get("/api/v1/task-config").status_code == 404
    assert web_client.get("/api/v1/task-states").status_code == 404


def test_one_shot_jobs_crud_flow(web_client, test_memory_db_path):
    from obsidian_ai_hub.scheduler_jobs import one_shot

    res = web_client.get("/api/v1/scheduler-jobs/one-shot-jobs")
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0}

    row = one_shot.register_one_shot_job("printf hi", agent_id="a1", session_id="s1", run_id="r1")
    job_id = row["job_id"]

    res = web_client.get("/api/v1/scheduler-jobs/one-shot-jobs")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["job_id"] == job_id
    assert item["status"] == "queued"
    assert item["agent_id"] == "a1"

    res = web_client.get(f"/api/v1/scheduler-jobs/one-shot-jobs/{job_id}")
    assert res.status_code == 200
    detail = res.json()
    assert detail["job_id"] == job_id
    assert detail["segments"] == []

    res = web_client.get("/api/v1/scheduler-jobs/one-shot-jobs/missing")
    assert res.status_code == 404

    res = web_client.post(f"/api/v1/scheduler-jobs/one-shot-jobs/{job_id}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"

    # Cancelling a terminal job is rejected.
    res = web_client.post(f"/api/v1/scheduler-jobs/one-shot-jobs/{job_id}/cancel")
    assert res.status_code == 422

    res = web_client.post("/api/v1/scheduler-jobs/one-shot-jobs/missing/cancel")
    assert res.status_code == 404


def test_one_shot_jobs_require_token(clean_job_env, api_token):
    from obsidian_ai_hub.web.app import create_app
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    client = TestClient(app)

    res = client.get("/api/v1/scheduler-jobs/one-shot-jobs")
    assert res.status_code == 401

    res = client.get("/api/v1/scheduler-jobs/job-states")
    assert res.status_code == 401


def test_job_states_api(web_client, test_memory_db_path):
    from obsidian_ai_hub.utils import execution_logger

    execution_logger.upsert_job_state("merge_inbox", result={"processed": 0, "skipped": 0, "failed": 0})

    res = web_client.get("/api/v1/scheduler-jobs/job-states")
    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["job_id"] == "merge_inbox"


def test_corrupt_jobs_yaml_returns_500_and_never_overwrites(clean_job_env, web_client):
    job_file, _ = clean_job_env
    job_file.write_text("id: [unclosed\n  broken: : :", encoding="utf-8")

    res = web_client.get("/api/v1/scheduler-jobs/recurring-jobs")
    assert res.status_code == 500

    res = web_client.put(
        "/api/v1/scheduler-jobs/recurring-jobs", json={"revision": "", "jobs": []}
    )
    assert res.status_code == 500

    # The corrupt file was not overwritten by the failed save flow.
    assert job_file.read_text(encoding="utf-8").startswith("id: [unclosed")
