"""Workflow API and store tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.workflow import store as workflow_store


@pytest.fixture
def client(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


def _linear_graph():
    nodes = [
        {
            "node_id": "n_cap",
            "node_type": "capability",
            "config": {"capability_key": "vault_search", "inputs": {"query": "x"}},
        },
        {
            "node_id": "n_end",
            "node_type": "terminal",
            "config": {"outcome": "success"},
        },
    ]
    edges = [
        {
            "edge_id": "e1",
            "source_node_id": "n_cap",
            "target_node_id": "n_end",
            "order_index": 0,
        }
    ]
    return nodes, edges


def test_workflow_api_roundtrip(test_memory_db_path, client):
    task_store.sync_capabilities()

    created = client.post(
        "/api/v1/workflows", json={"name": "wf", "description": "d"}
    )
    assert created.status_code == 201
    workflow = created.json()
    revision_id = workflow["revision"]["revision_id"]

    nodes, edges = _linear_graph()
    updated = client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": {"type": "object"}, "nodes": nodes, "edges": edges},
    )
    assert updated.status_code == 200

    validated = client.post(f"/api/v1/workflows/revisions/{revision_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["valid"] is True

    published = client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    run_response = client.post(
        f"/api/v1/workflows/revisions/{revision_id}/runs", json={"inputs": {}}
    )
    assert run_response.status_code == 201
    run = run_response.json()
    assert run["status"] == "queued"

    detail = client.get(f"/api/v1/workflows/runs/{run['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run["run_id"]

    cancelled = client.post(f"/api/v1/workflows/runs/{run['run_id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_invalid_graph_is_rejected_on_publish(test_memory_db_path, client):
    task_store.sync_capabilities()
    created = client.post("/api/v1/workflows", json={"name": "bad"})
    revision_id = created.json()["revision"]["revision_id"]
    nodes, edges = _linear_graph()
    edges.append(
        {
            "edge_id": "e2",
            "source_node_id": "n_end",
            "target_node_id": "n_cap",
            "order_index": 0,
        }
    )
    client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": {"type": "object"}, "nodes": nodes, "edges": edges},
    )
    published = client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")
    assert published.status_code == 422


def test_store_lifecycle_and_purge(test_memory_db_path):
    workflow = workflow_store.create_workflow("store", inputs_schema={"type": "object"})
    revision = workflow["revision"]
    nodes, edges = _linear_graph()
    workflow_store.set_revision_graph(revision["revision_id"], nodes, edges)
    workflow_store.publish_revision(revision["revision_id"])

    run = workflow_store.create_run(
        workflow["workflow_id"], revision["revision_id"], {"a": 1}
    )
    assert workflow_store.get_run(run["run_id"])["status"] == "queued"
    claimed = workflow_store.claim_run("inst-1")
    assert claimed is not None
    workflow_store.transition_run_status(
        run["run_id"], "completed", result_summary="ok"
    )
    finished = workflow_store.get_run(run["run_id"])
    assert finished["status"] == "completed"
    assert finished["finished_at"] is not None

    # Not yet old enough to purge.
    assert workflow_store.purge_terminal_runs(days=30) == 0
    # Force old finished_at to verify retention deletion.
    from obsidian_ai_hub.database import get_db_connection

    with get_db_connection() as conn:
        conn.execute(
            "UPDATE workflow_runs SET finished_at = '2000-01-01T00:00:00+00:00' "
            "WHERE run_id = ?;",
            (run["run_id"],),
        )
    assert workflow_store.purge_terminal_runs(days=30) == 1
    assert workflow_store.get_run(run["run_id"]) is None


def test_claim_returns_none_when_idle(test_memory_db_path):
    assert workflow_store.claim_run("inst-idle") is None


def test_approval_required_flow(test_memory_db_path, client):
    task_store.sync_capabilities()
    created = client.post("/api/v1/workflows", json={"name": "approve"})
    revision_id = created.json()["revision"]["revision_id"]
    nodes = [
        {
            "node_id": "n_write",
            "node_type": "capability",
            "config": {
                "capability_key": "vault_write_file",
                "inputs": {
                    "relative_path": "x.md",
                    "content": "hi",
                    "overwrite": True,
                },
            },
        },
        {"node_id": "n_end", "node_type": "terminal", "config": {"outcome": "success"}},
    ]
    edges = [
        {
            "edge_id": "e1",
            "source_node_id": "n_write",
            "target_node_id": "n_end",
            "order_index": 0,
        }
    ]
    client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": {"type": "object"}, "nodes": nodes, "edges": edges},
    )
    published = client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")
    assert published.status_code == 200

    run = client.post(
        f"/api/v1/workflows/revisions/{revision_id}/runs", json={"inputs": {}}
    ).json()
    # A plan_required capability inserts the run directly in waiting_approval.
    assert run["status"] == "waiting_approval"

    approved = client.post(f"/api/v1/workflows/runs/{run['run_id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "queued"


def test_run_inputs_validated_against_schema(test_memory_db_path, client):
    created = client.post(
        "/api/v1/workflows",
        json={
            "name": "inputs",
            "inputs_schema": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        },
    )
    revision_id = created.json()["revision"]["revision_id"]
    nodes, edges = _linear_graph()
    client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={
            "inputs_schema": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
            "nodes": nodes,
            "edges": edges,
        },
    )
    client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")
    bad = client.post(
        f"/api/v1/workflows/revisions/{revision_id}/runs", json={"inputs": {}}
    )
    assert bad.status_code == 422


def test_hitl_wait_node_publishes_without_task_catalog(test_memory_db_path, client):
    created = client.post("/api/v1/workflows", json={"name": "hitl"})
    revision_id = created.json()["revision"]["revision_id"]
    nodes = [
        {
            "node_id": "n_hitl",
            "node_type": "capability",
            "config": {
                "capability_key": "hitl_wait",
                "inputs": {"question": "続行しますか？"},
            },
        },
        {"node_id": "n_end", "node_type": "terminal", "config": {"outcome": "success"}},
    ]
    edges = [
        {
            "edge_id": "e1",
            "source_node_id": "n_hitl",
            "target_node_id": "n_end",
            "order_index": 0,
        }
    ]
    client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": {"type": "object"}, "nodes": nodes, "edges": edges},
    )
    validated = client.post(f"/api/v1/workflows/revisions/{revision_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    published = client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")
    assert published.status_code == 200
    run = client.post(
        f"/api/v1/workflows/revisions/{revision_id}/runs", json={"inputs": {}}
    ).json()
    # hitl_wait is auto policy, so the run is queued rather than awaiting approval.
    assert run["status"] == "queued"
