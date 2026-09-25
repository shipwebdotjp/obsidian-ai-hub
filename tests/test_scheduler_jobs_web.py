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


def test_recurring_agent_source_roundtrip_and_human_edit(clean_job_env, web_client):
    job_file, _ = clean_job_env
    recurring.atomic_write_yaml(
        job_file,
        [
            {
                "id": "agent_job",
                "enabled": True,
                "schedule": {"type": "minutely", "second": 0},
                "command": "printf agent",
                "note": "hand written",
                "agent_source": {"agent_id": "agent-1", "session_id": "s1"},
            },
            {
                "id": "manual",
                "enabled": True,
                "schedule": {"type": "minutely"},
                "command": "printf manual",
            },
        ],
    )

    body = web_client.get("/api/v1/scheduler-jobs/recurring-jobs").json()
    agent = next(j for j in body["jobs"] if j["id"] == "agent_job")
    assert agent["agent_source"]["agent_id"] == "agent-1"
    manual = next(j for j in body["jobs"] if j["id"] == "manual")
    assert manual["agent_source"] is None

    # Same-value PUT keeps ownership and unknown metadata.
    same = [
        {
            "id": "agent_job",
            "enabled": True,
            "schedule": {"type": "minutely", "second": 0},
            "command": "printf agent",
        },
        {
            "id": "manual",
            "enabled": True,
            "schedule": {"type": "minutely"},
            "command": "printf manual",
            # A client cannot self-assign ownership.
            "agent_source": {"agent_id": "evil"},
        },
    ]
    res = web_client.put(
        "/api/v1/scheduler-jobs/recurring-jobs",
        json={"revision": body["revision"], "jobs": same},
    )
    assert res.status_code == 200
    saved = {j["id"]: j for j in yaml.safe_load(open(job_file))}
    assert saved["agent_job"]["agent_source"]["agent_id"] == "agent-1"
    assert saved["agent_job"]["note"] == "hand written"
    assert "agent_source" not in saved["manual"]

    # A meaningful human edit revokes ownership.
    rev = res.json()["revision"]
    edited = [
        {
            "id": "agent_job",
            "enabled": True,
            "schedule": {"type": "minutely", "second": 0},
            "command": "printf changed",
        },
        {
            "id": "manual",
            "enabled": True,
            "schedule": {"type": "minutely"},
            "command": "printf manual",
        },
    ]
    res = web_client.put(
        "/api/v1/scheduler-jobs/recurring-jobs",
        json={"revision": rev, "jobs": edited},
    )
    assert res.status_code == 200
    saved = {j["id"]: j for j in yaml.safe_load(open(job_file))}
    assert "agent_source" not in saved["agent_job"]
    assert saved["agent_job"]["note"] == "hand written"


def test_recurring_corrupt_agent_source_does_not_500(clean_job_env, web_client):
    job_file, _ = clean_job_env
    recurring.atomic_write_yaml(
        job_file,
        [
            {
                "id": "corrupt",
                "enabled": True,
                "schedule": {"type": "minutely"},
                "command": "printf x",
                "agent_source": {"agent_id": "a", "session_id": 123},
            }
        ],
    )
    res = web_client.get("/api/v1/scheduler-jobs/recurring-jobs")
    assert res.status_code == 200
    assert res.json()["jobs"][0]["agent_source"] is None


def test_update_recurring_jobs_stale_revision_writes_nothing(clean_job_env, web_client):
    job_file, _ = clean_job_env
    original = [
        {
            "id": "kept",
            "enabled": True,
            "schedule": {"type": "minutely"},
            "command": "printf kept",
        }
    ]
    recurring.atomic_write_yaml(job_file, original)
    before = open(job_file, "rb").read()

    res = web_client.put(
        "/api/v1/scheduler-jobs/recurring-jobs",
        json={
            "revision": "stale",
            "jobs": [
                {
                    "id": "replaced",
                    "enabled": True,
                    "schedule": {"type": "hourly", "minute": 0},
                    "command": "printf replaced",
                }
            ],
        },
    )
    assert res.status_code == 409
    assert open(job_file, "rb").read() == before


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

    res = client.post("/api/v1/scheduler-jobs/recurring-jobs/job_cmd/run")
    assert res.status_code == 401


def test_corrupt_jobs_yaml_returns_500_and_never_overwrites(clean_job_env, web_client):
    job_file, _ = clean_job_env
    job_file.write_text("id: [unclosed\n  broken: : :", encoding="utf-8")

    res = web_client.get("/api/v1/scheduler-jobs/recurring-jobs")
    assert res.status_code == 500

    res = web_client.put(
        "/api/v1/scheduler-jobs/recurring-jobs", json={"revision": "", "jobs": []}
    )
    assert res.status_code == 500

    res = web_client.post("/api/v1/scheduler-jobs/recurring-jobs/job_cmd/run")
    assert res.status_code == 500

    # The corrupt file was not overwritten by the failed save flow.
    assert job_file.read_text(encoding="utf-8").startswith("id: [unclosed")


def _publish_terminal_workflow(name="wf"):
    from obsidian_ai_hub.workflow import store as workflow_store

    wf = workflow_store.create_workflow(name, inputs_schema={"type": "object"})
    rev = wf["revision"]
    workflow_store.set_revision_graph(
        rev["revision_id"],
        [
            {
                "node_id": "t",
                "node_type": "terminal",
                "config": {"outcome": "success"},
                "parent_loop_node_id": None,
                "ui_position": None,
            }
        ],
        [],
    )
    workflow_store.publish_revision(rev["revision_id"])
    return wf["workflow_id"]


def test_create_one_shot_workflow_job_endpoint(
    clean_job_env, web_client, test_memory_db_path
):
    workflow_id = _publish_terminal_workflow()

    res = web_client.post(
        "/api/v1/scheduler-jobs/one-shot-jobs",
        json={"workflow_id": workflow_id, "inputs": {}},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["target_kind"] == "workflow"
    assert body["workflow_id"] == workflow_id
    assert body["status"] == "queued"


def test_create_one_shot_workflow_job_rejects_unpublished(
    clean_job_env, web_client, test_memory_db_path
):
    res = web_client.post(
        "/api/v1/scheduler-jobs/one-shot-jobs",
        json={"workflow_id": "wf_missing", "inputs": {}},
    )
    assert res.status_code == 422


def test_recurring_jobs_hide_corrupt_workflow_target(
    clean_job_env, web_client, test_memory_db_path
):
    job_file, _ = clean_job_env
    recurring.atomic_write_yaml(
        job_file,
        [
            {
                "id": "bad",
                "enabled": True,
                "schedule": {"type": "daily", "hour": 1},
                "workflow": {"inputs": {}},
            }
        ],
    )
    res = web_client.get("/api/v1/scheduler-jobs/recurring-jobs")
    assert res.status_code == 200, res.text
    assert res.json()["jobs"][0]["workflow"] is None


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _ok_executor(stdout="ok"):
    calls = []

    def run(args, cwd=None):
        calls.append((list(args), cwd))
        return _Proc(0, stdout, "")

    run.calls = calls
    return run


def _run_now_job_entry(job_id="job_cmd", *, command=None, workflow=None, enabled=True):
    entry = {
        "id": job_id,
        "enabled": enabled,
        "schedule": {"type": "daily", "hour": 3, "minute": 0},
    }
    if workflow is not None:
        entry["workflow"] = workflow
    else:
        entry["command"] = command or "printf run-now"
    return entry


def test_run_recurring_job_now_command_scenario(
    clean_job_env, web_client, test_memory_db_path, monkeypatch
):
    """Recurring job -> run-now -> queued manual row -> one runner execution.

    The operation-scenario contract for the manual run of a disabled job: the
    target is resolved from the current YAML (never from the client), the
    schedule state is untouched, duplicates are refused, and the runner runs
    the copied command exactly once.
    """
    from obsidian_ai_hub import job_runner
    from obsidian_ai_hub.scheduler_jobs import one_shot

    job_file, _ = clean_job_env
    recurring.atomic_write_yaml(job_file, [_run_now_job_entry(enabled=False)])

    kicks = []
    monkeypatch.setattr(
        job_runner, "spawn_cycle_process", lambda: kicks.append(1) or 1234
    )

    res = web_client.post("/api/v1/scheduler-jobs/recurring-jobs/job_cmd/run")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["target_kind"] == "command"
    assert body["command"] == "printf run-now"
    assert body["status"] == "queued"
    assert body["source"] == "manual"
    assert body["source_job_id"] == "job_cmd"
    assert kicks == [1]

    # A duplicate click while queued is rejected without a second row.
    res = web_client.post("/api/v1/scheduler-jobs/recurring-jobs/job_cmd/run")
    assert res.status_code == 409

    # Manual runs do not touch the recurring job's arming/last_run state.
    assert recurring.load_state() == {}

    executor = _ok_executor()
    finished = one_shot.run_due_one_shot_jobs(executor=executor)
    assert [j["job_id"] for j in finished] == [body["job_id"]]
    assert len(executor.calls) == 1
    assert executor.calls[0][0] == ["printf", "run-now"]
    done = one_shot.get_one_shot_job(body["job_id"])
    assert done["status"] == "succeeded"
    assert done["exit_code"] == 0

    # A terminal manual run frees the recurring job for another manual run.
    res = web_client.post("/api/v1/scheduler-jobs/recurring-jobs/job_cmd/run")
    assert res.status_code == 201
    assert res.json()["job_id"] != body["job_id"]


def test_run_recurring_job_now_ignores_client_target_payload(
    clean_job_env, web_client, test_memory_db_path, monkeypatch
):
    from obsidian_ai_hub import job_runner

    job_file, _ = clean_job_env
    recurring.atomic_write_yaml(
        job_file, [_run_now_job_entry(command="printf safe")]
    )
    monkeypatch.setattr(job_runner, "spawn_cycle_process", lambda: None)

    res = web_client.post(
        "/api/v1/scheduler-jobs/recurring-jobs/job_cmd/run",
        json={"command": "printf hacked", "workflow_id": "wf_x", "inputs": {"a": 1}},
    )
    assert res.status_code == 201, res.text
    assert res.json()["command"] == "printf safe"
    assert res.json()["workflow_id"] is None


def test_run_recurring_job_now_spawn_failure_keeps_queued_row(
    clean_job_env, web_client, test_memory_db_path, monkeypatch
):
    """A failed immediate kick must not abort the request or drop the queued row."""
    from obsidian_ai_hub import job_runner
    from obsidian_ai_hub.scheduler_jobs import one_shot

    job_file, _ = clean_job_env
    recurring.atomic_write_yaml(job_file, [_run_now_job_entry()])

    def boom():
        raise OSError("fork failed")

    monkeypatch.setattr(job_runner, "spawn_cycle_process", boom)

    res = web_client.post("/api/v1/scheduler-jobs/recurring-jobs/job_cmd/run")
    assert res.status_code == 201, res.text
    row = one_shot.get_one_shot_job(res.json()["job_id"])
    assert row is not None
    assert row["status"] == "queued"

    # The queued manual row still runs on the next runner cycle.
    executor = _ok_executor()
    finished = one_shot.run_due_one_shot_jobs(executor=executor)
    assert [j["job_id"] for j in finished] == [res.json()["job_id"]]
    assert len(executor.calls) == 1


def test_run_recurring_job_now_workflow_scenario(
    clean_job_env, web_client, test_memory_db_path, monkeypatch
):
    from obsidian_ai_hub import job_runner
    from obsidian_ai_hub.scheduler_jobs import one_shot

    workflow_id = _publish_terminal_workflow()
    job_file, _ = clean_job_env
    recurring.atomic_write_yaml(
        job_file,
        [
            _run_now_job_entry(
                job_id="job_wf",
                workflow={"workflow_id": workflow_id, "inputs": {}},
            )
        ],
    )
    monkeypatch.setattr(job_runner, "spawn_cycle_process", lambda: None)

    res = web_client.post("/api/v1/scheduler-jobs/recurring-jobs/job_wf/run")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["target_kind"] == "workflow"
    assert body["workflow_id"] == workflow_id
    assert body["source"] == "manual"
    assert body["source_job_id"] == "job_wf"

    res = web_client.post("/api/v1/scheduler-jobs/recurring-jobs/job_wf/run")
    assert res.status_code == 409

    # The runner dispatches the queued one-shot into a Run (queue terminal).
    finished = one_shot.run_due_one_shot_jobs()
    assert [j["job_id"] for j in finished] == [body["job_id"]]
    assert finished[0]["status"] == "dispatched"
    assert finished[0]["workflow_run_id"]


def test_run_recurring_job_now_errors(
    clean_job_env, web_client, test_memory_db_path, monkeypatch
):
    from obsidian_ai_hub import job_runner

    job_file, _ = clean_job_env
    monkeypatch.setattr(job_runner, "spawn_cycle_process", lambda: None)

    res = web_client.post("/api/v1/scheduler-jobs/recurring-jobs/missing/run")
    assert res.status_code == 404

    # A job with neither command nor workflow is not runnable.
    recurring.atomic_write_yaml(
        job_file, [{"id": "bad", "enabled": True, "schedule": {"type": "daily"}}]
    )
    res = web_client.post("/api/v1/scheduler-jobs/recurring-jobs/bad/run")
    assert res.status_code == 422

    # A workflow target without a published Revision is rejected up front.
    recurring.atomic_write_yaml(
        job_file,
        [_run_now_job_entry(job_id="job_wf", workflow={"workflow_id": "wf_missing"})],
    )
    res = web_client.post("/api/v1/scheduler-jobs/recurring-jobs/job_wf/run")
    assert res.status_code == 422
