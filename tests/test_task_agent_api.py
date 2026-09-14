from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.tasks import store
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def client(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


@pytest.fixture
def anon_client(api_token):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app)


def _waiting_task():
    task = store.create_task("api job")
    store.claim_task("worker-test", "planning")
    store.create_plan(task["task_id"], {"purpose": "p", "steps": []}, {})
    store.transition_task_status(task["task_id"], "waiting_approval")
    return task


def test_list_and_detail(test_memory_db_path, client):
    response = client.get("/api/v1/task-agent/tasks")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}

    task = store.create_task("listed job")
    response = client.get("/api/v1/task-agent/tasks")
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["task_id"] == task["task_id"]
    assert data["items"][0]["status"] == "queued"

    response = client.get("/api/v1/task-agent/tasks", params={"status": "running"})
    assert response.json() == {"items": [], "total": 0}

    response = client.get(f"/api/v1/task-agent/tasks/{task['task_id']}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["task"]["task_id"] == task["task_id"]
    assert detail["plans"] == []
    assert detail["events"] == []

    response = client.get("/api/v1/task-agent/tasks/task_missing")
    assert response.status_code == 404


def test_approve_and_reject(test_memory_db_path, client):
    task = _waiting_task()
    response = client.post(f"/api/v1/task-agent/tasks/{task['task_id']}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"

    response = client.post(f"/api/v1/task-agent/tasks/{task['task_id']}/approve")
    assert response.status_code == 400

    task2 = _waiting_task()
    response = client.post(
        f"/api/v1/task-agent/tasks/{task2['task_id']}/reject", json={}
    )
    assert response.status_code == 422
    response = client.post(
        f"/api/v1/task-agent/tasks/{task2['task_id']}/reject",
        json={"reason": "  "},
    )
    assert response.status_code == 422
    response = client.post(
        f"/api/v1/task-agent/tasks/{task2['task_id']}/reject",
        json={"reason": "too vague"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"

    response = client.post("/api/v1/task-agent/tasks/task_missing/approve")
    assert response.status_code == 404


def test_cancel_states(test_memory_db_path, client):
    queued = store.create_task("cancel queued")
    response = client.post(f"/api/v1/task-agent/tasks/{queued['task_id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    running = store.create_task("cancel running")
    store.claim_task("worker-test", "planning")
    store.transition_task_status(running["task_id"], "running")
    store.set_active_child(running["task_id"], "agent", "arun_missing")
    response = client.post(f"/api/v1/task-agent/tasks/{running['task_id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelling"

    response = client.post(f"/api/v1/task-agent/tasks/{queued['task_id']}/cancel")
    assert response.status_code == 400

    response = client.post("/api/v1/task-agent/tasks/task_missing/cancel")
    assert response.status_code == 404


def test_replan_only_interrupted(test_memory_db_path, client):
    task = store.create_task("replan job")
    store.claim_task("worker-test", "planning")
    store.transition_task_status(task["task_id"], "interrupted")
    response = client.post(f"/api/v1/task-agent/tasks/{task['task_id']}/replan")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"

    queued = store.create_task("not interrupted")
    response = client.post(f"/api/v1/task-agent/tasks/{queued['task_id']}/replan")
    assert response.status_code == 400


def test_capabilities_api(test_memory_db_path, client):
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

    response = client.get("/api/v1/task-agent/capabilities")
    assert response.status_code == 200
    capabilities = response.json()
    assert len(capabilities) == len(get_capability_definitions())
    assert all("capability_key" in c for c in capabilities)
    by_key = {c["capability_key"]: c for c in capabilities}
    assert by_key["run_shell"]["approval_policy"] == "plan_required"
    assert by_key["run_shell"]["label"]
    assert by_key["web_search"]["approval_policy"] == "auto"

    response = client.put(
        "/api/v1/task-agent/capabilities/run_shell", json={"enabled": False}
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["label"]

    response = client.put(
        "/api/v1/task-agent/capabilities/coding_cli", json={"enabled": False}
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    response = client.put(
        "/api/v1/task-agent/capabilities/coding_cli",
        json={"approval_policy": "bogus"},
    )
    assert response.status_code == 422

    response = client.put(
        "/api/v1/task-agent/capabilities/ask_user", json={"enabled": False}
    )
    assert response.status_code == 404

    response = client.put("/api/v1/task-agent/capabilities/coding_cli", json={})
    assert response.status_code == 422


def test_auth_required(test_memory_db_path, anon_client):
    assert anon_client.get("/api/v1/task-agent/tasks").status_code == 401
    assert anon_client.get("/api/v1/task-agent/capabilities").status_code == 401
