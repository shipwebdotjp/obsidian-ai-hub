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


def test_workflow_bridge_hidden_from_list_but_detail_available(
    test_memory_db_path, client
):
    user_task = store.create_task("user listed task")
    bridge = store.create_task(
        "Workflow run wrun_api node n (research_agent)",
        origin=store.TASK_ORIGIN_WORKFLOW,
    )
    response = client.get("/api/v1/task-agent/tasks")
    data = response.json()
    listed_ids = {item["task_id"] for item in data["items"]}
    assert user_task["task_id"] in listed_ids
    assert bridge["task_id"] not in listed_ids
    assert data["total"] == len(listed_ids)

    # Bridge rows stay reachable for audit through the direct detail URL.
    response = client.get(f"/api/v1/task-agent/tasks/{bridge['task_id']}")
    assert response.status_code == 200
    assert response.json()["task"]["origin"] == "workflow"


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


def test_create_task(test_memory_db_path, client):
    response = client.post(
        "/api/v1/task-agent/tasks", json={"prompt_text": "Summarize this week"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["task_id"].startswith("task_")
    assert data["status"] == "queued"
    assert data["prompt_text"] == "Summarize this week"

    persisted = store.get_task(data["task_id"])
    assert persisted is not None
    assert persisted["status"] == "queued"


def test_create_task_validation(test_memory_db_path, client):
    assert (
        client.post("/api/v1/task-agent/tasks", json={"prompt_text": "  "}).status_code
        == 422
    )
    assert client.post("/api/v1/task-agent/tasks", json={}).status_code == 422
    assert (
        client.post(
            "/api/v1/task-agent/tasks",
            json={"prompt_text": "job", "unexpected": "field"},
        ).status_code
        == 422
    )


def test_auth_required(test_memory_db_path, anon_client):
    assert anon_client.get("/api/v1/task-agent/tasks").status_code == 401
    assert anon_client.get("/api/v1/task-agent/capabilities").status_code == 401
    assert (
        anon_client.post(
            "/api/v1/task-agent/tasks", json={"prompt_text": "job"}
        ).status_code
        == 401
    )


def _valid_project_stubs(monkeypatch):
    from obsidian_ai_hub.coding import backend as coding_backend
    from obsidian_ai_hub.web.services import projects as project_service

    def _list_projects():
        return [
            {
                "project_id": 7,
                "display_name": "Demo Seven",
                "normalized_name": "demo seven",
                "keywords": ["demo"],
                "project_path": "/repo/demo",
            },
            {
                "project_id": 11,
                "display_name": "Broken",
                "normalized_name": "broken",
                "keywords": [],
                "project_path": "/repo/broken",
            },
        ]

    def _detail(pid):
        return next((p for p in _list_projects() if p["project_id"] == pid), None)

    def _git_root(path):
        if path == "/repo/demo":
            return "/repo/demo"
        raise ValueError("not a git repo")

    monkeypatch.setattr(project_service, "list_projects", _list_projects)
    monkeypatch.setattr(project_service, "get_project_detail", _detail)
    monkeypatch.setattr(coding_backend, "validate_git_repo", _git_root)


def _waiting_target_task(prompt="target job"):
    """Create a task waiting for approval without relying on claim order."""
    task = store.create_task(prompt)
    store.transition_task_status(task["task_id"], "planning")
    store.create_plan(task["task_id"], {"purpose": "p", "steps": []}, {})
    store.transition_task_status(task["task_id"], "waiting_approval")
    return task


def test_project_resolution_changes_target(test_memory_db_path, client, monkeypatch):
    _valid_project_stubs(monkeypatch)
    task = _waiting_target_task()
    response = client.post(
        f"/api/v1/task-agent/tasks/{task['task_id']}/project-resolution",
        json={"kind": "project", "project_id": 7},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    events = store.list_task_events(task["task_id"])
    selected = [e for e in events if e["event_type"] == "target_resolution_selected"]
    assert len(selected) == 1
    assert selected[0]["payload"]["project_id"] == 7
    assert selected[0]["payload"]["kind"] == "project"
    plans = store.list_plans(task["task_id"])
    assert plans[0]["status"] == "superseded"

    response = client.post(
        f"/api/v1/task-agent/tasks/{task['task_id']}/project-resolution",
        json={"kind": "general"},
    )
    assert response.status_code == 400

    task2 = _waiting_target_task("target job 2")
    response = client.post(
        f"/api/v1/task-agent/tasks/{task2['task_id']}/project-resolution",
        json={"kind": "general"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_project_resolution_rejects_invalid(test_memory_db_path, client, monkeypatch):
    _valid_project_stubs(monkeypatch)
    task = _waiting_target_task()
    # Deleted project (not in registry).
    response = client.post(
        f"/api/v1/task-agent/tasks/{task['task_id']}/project-resolution",
        json={"kind": "project", "project_id": 99},
    )
    assert response.status_code == 400
    # Invalid git root.
    response = client.post(
        f"/api/v1/task-agent/tasks/{task['task_id']}/project-resolution",
        json={"kind": "project", "project_id": 11},
    )
    assert response.status_code == 400
    # Malformed bodies.
    assert (
        client.post(
            f"/api/v1/task-agent/tasks/{task['task_id']}/project-resolution",
            json={"kind": "project"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/task-agent/tasks/{task['task_id']}/project-resolution",
            json={"kind": "general", "project_id": 7},
        ).status_code
        == 422
    )
    # Task still waiting: no selection persisted, plan still pending.
    events = store.list_task_events(task["task_id"])
    assert [e for e in events if e["event_type"] == "target_resolution_selected"] == []
    assert store.get_task(task["task_id"])["status"] == "waiting_approval"

    queued = store.create_task("not waiting")
    response = client.post(
        f"/api/v1/task-agent/tasks/{queued['task_id']}/project-resolution",
        json={"kind": "general"},
    )
    assert response.status_code == 400

    response = client.post(
        "/api/v1/task-agent/tasks/task_missing/project-resolution",
        json={"kind": "general"},
    )
    assert response.status_code == 404


def test_target_options_returns_valid_git_projects_only(
    test_memory_db_path, client, monkeypatch
):
    _valid_project_stubs(monkeypatch)
    response = client.get("/api/v1/task-agent/target-options")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items == [
        {
            "project_id": 7,
            "name": "Demo Seven",
            "git_root": "/repo/demo",
            "keywords": ["demo"],
        }
    ]
