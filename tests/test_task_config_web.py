# ruff: noqa: E402
import sys
from unittest.mock import MagicMock

# Mock macOS-specific modules before importing obsidian_ai_hub
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
import yaml
from datetime import datetime
from fastapi.testclient import TestClient

from obsidian_ai_hub.utils import config
from obsidian_ai_hub import task_runner


@pytest.fixture
def clean_task_env(tmp_path, monkeypatch):
    # Set up isolation for tasks & state files
    test_state_file = tmp_path / "last_run.json"
    monkeypatch.setattr(task_runner, "STATE_FILE", test_state_file)
    monkeypatch.setattr(config, "TASK_RUN_STATE_PATH", test_state_file)

    test_task_file = tmp_path / "tasks.test.yml"
    monkeypatch.setattr(task_runner, "TEST_TASK_FILE", test_task_file)
    monkeypatch.setattr(task_runner, "LOCAL_TASK_FILE", test_task_file)
    monkeypatch.setattr(task_runner, "DEFAULT_TASK_FILE", test_task_file)

    # Set up config file locks
    monkeypatch.setattr(task_runner, "LOCK_FILE", tmp_path / ".task-config.lock")
    monkeypatch.setattr(task_runner, "RUNNER_LOCK_FILE", tmp_path / ".task-runner.lock")

    monkeypatch.setattr(config, "IS_TEST_ENV", True)

    return test_task_file, test_state_file


@pytest.fixture
def web_client(clean_task_env):
    from obsidian_ai_hub.web.app import create_app
    app = create_app(host="127.0.0.1", port=0, token="")
    return TestClient(app)


def test_get_task_config_empty(clean_task_env, web_client):
    task_file, _ = clean_task_env
    # Initialize task file
    task_runner.atomic_write_yaml(task_file, [])

    res = web_client.get("/api/v1/task-config")
    assert res.status_code == 200
    body = res.json()
    assert body["tasks"] == []
    assert body["filepath"] == str(task_file)
    assert len(body["revision"]) == 64  # SHA-256 hash length


def test_get_task_config_with_preset_and_custom(clean_task_env, web_client):
    task_file, _ = clean_task_env
    initial_tasks = [
        {
            "id": "task_preset",
            "enabled": True,
            "schedule": {"type": "minutely", "second": 0},
            "command": "uv --directory /some/base run -m obsidian_ai_hub --merge-inbox"
        },
        {
            "id": "task_custom",
            "enabled": False,
            "schedule": {"type": "daily", "hour": 12, "minute": 30},
            "command": "echo 'arbitrary command'"
        }
    ]
    task_runner.atomic_write_yaml(task_file, initial_tasks)

    res = web_client.get("/api/v1/task-config")
    assert res.status_code == 200
    body = res.json()
    assert len(body["tasks"]) == 2

    preset_task = next(t for t in body["tasks"] if t["id"] == "task_preset")
    assert preset_task["is_preset"] is True
    assert preset_task["preset_flag"] == "--merge-inbox"
    assert preset_task["preset_name"] == "Inbox merge"
    assert preset_task["next_run"] is not None

    custom_task = next(t for t in body["tasks"] if t["id"] == "task_custom")
    assert custom_task["is_preset"] is False
    assert custom_task["preset_flag"] is None
    assert custom_task["next_run"] is not None


def test_localhost_restriction(clean_task_env):
    from obsidian_ai_hub.web.app import create_app
    # Test client using client host parameter mock to simulate LAN access
    app = create_app(host="127.0.0.1", port=0, token="")
    client = TestClient(app)

    # loopback works
    res = client.get("/api/v1/task-config")
    assert res.status_code == 200

    # LAN / Non-localhost block
    lan_client = TestClient(app, client=("192.168.1.5", 50000))
    res = lan_client.get("/api/v1/task-config")
    assert res.status_code == 403
    assert "Forbidden" in res.json()["detail"]


def test_update_task_config_success_and_arming(clean_task_env, web_client):
    task_file, state_file = clean_task_env

    # 1. Write initial state
    initial_tasks = [
        {
            "id": "task_unchanged",
            "enabled": True,
            "schedule": {"type": "hourly", "minute": 0},
            "command": "uv --directory /app run -m obsidian_ai_hub --backup"
        },
        {
            "id": "task_to_change",
            "enabled": True,
            "schedule": {"type": "hourly", "minute": 30},
            "command": "echo 'original command'"
        }
    ]
    task_runner.atomic_write_yaml(task_file, initial_tasks)

    # Set historical last run times
    old_now = datetime(2026, 1, 1, 10, 0, 0)
    task_runner.save_state({
        "task_unchanged": old_now,
        "task_to_change": old_now
    })

    # Fetch initial revision
    get_res = web_client.get("/api/v1/task-config")
    rev = get_res.json()["revision"]

    # 2. Update via PUT
    updated_tasks = [
        {
            "id": "task_unchanged",
            "enabled": True,
            "schedule": {"type": "hourly", "minute": 0},
            "command": "uv --directory /app run -m obsidian_ai_hub --backup"
        },
        {
            "id": "task_to_change",
            "enabled": True,
            "schedule": {"type": "hourly", "minute": 45}, # Schedule changed!
            "command": "echo 'original command'"
        },
        {
            "id": "task_new",
            "enabled": True,
            "schedule": {"type": "minutely", "second": 10}, # New task!
            "command": "echo 'new command'"
        }
    ]

    put_res = web_client.put("/api/v1/task-config", json={
        "revision": rev,
        "tasks": updated_tasks
    })
    assert put_res.status_code == 200
    assert put_res.json()["success"] is True
    new_rev = put_res.json()["revision"]
    assert new_rev != rev

    # Verify atomic file update
    with open(task_file, "r") as f:
        saved_tasks = yaml.safe_load(f)
    assert len(saved_tasks) == 3

    # Verify arming in state
    state = task_runner.load_state()
    # task_unchanged should remain old_now (no arming!)
    assert state["task_unchanged"] == old_now
    # task_to_change and task_new should be armed with today's datetime (now)
    assert state["task_to_change"] > old_now
    assert state["task_new"] > old_now


def test_update_task_config_conflict(clean_task_env, web_client):
    task_file, _ = clean_task_env
    task_runner.atomic_write_yaml(task_file, [])

    # Put with wrong revision
    res = web_client.put("/api/v1/task-config", json={
        "revision": "mismatched-revision-hash",
        "tasks": []
    })
    assert res.status_code == 409
    assert "Conflict" in res.json()["detail"]


def test_update_task_config_validation_errors(clean_task_env, web_client):
    task_file, _ = clean_task_env
    task_runner.atomic_write_yaml(task_file, [])

    get_res = web_client.get("/api/v1/task-config")
    rev = get_res.json()["revision"]

    # 1. Duplicate IDs
    invalid_tasks = [
        {"id": "dup", "schedule": {"type": "minutely"}, "command": "echo 1"},
        {"id": "dup", "schedule": {"type": "minutely"}, "command": "echo 2"}
    ]
    res = web_client.put("/api/v1/task-config", json={"revision": rev, "tasks": invalid_tasks})
    assert res.status_code == 422

    # 2. Invalid cron
    invalid_tasks = [
        {"id": "t1", "schedule": {"type": "minutely", "second": 100}, "command": "echo 1"}
    ]
    res = web_client.put("/api/v1/task-config", json={"revision": rev, "tasks": invalid_tasks})
    assert res.status_code == 422

    # 3. Unrelated fields
    invalid_tasks = [
        {"id": "t2", "schedule": {"type": "minutely", "day": 10}, "command": "echo 1"}
    ]
    res = web_client.put("/api/v1/task-config", json={"revision": rev, "tasks": invalid_tasks})
    assert res.status_code == 422

    # 4. Command syntax (unclosed quote)
    invalid_tasks = [
        {"id": "t3", "schedule": {"type": "minutely"}, "command": "echo 'unclosed quote"}
    ]
    res = web_client.put("/api/v1/task-config", json={"revision": rev, "tasks": invalid_tasks})
    assert res.status_code == 422


def test_preview_command_success(web_client):
    res = web_client.post("/api/v1/task-config/preview", json={
        "command": "cd /app/projects && uv run python -m test_module --args"
    })
    assert res.status_code == 200
    body = res.json()
    assert len(body["segments"]) == 1
    assert body["segments"][0]["cwd"] == "/app/projects"
    assert body["segments"][0]["args"] == ["uv", "run", "python", "-m", "test_module", "--args"]
    assert body["is_preset"] is False


def test_preview_command_preset(web_client):
    res = web_client.post("/api/v1/task-config/preview", json={
        "command": "uv --directory /app run -m obsidian_ai_hub --merge-inbox"
    })
    assert res.status_code == 200
    body = res.json()
    assert body["is_preset"] is True
    assert body["preset_flag"] == "--merge-inbox"
    assert body["preset_name"] == "Inbox merge"


def test_preview_command_error(web_client):
    res = web_client.post("/api/v1/task-config/preview", json={
        "command": "echo \"unclosed quote"
    })
    assert res.status_code == 422
