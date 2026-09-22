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


def test_create_revision_clones_explicit_source_with_loop(test_memory_db_path):
    workflow = workflow_store.create_workflow("clone-loop")
    source = workflow["revision"]
    nodes = [
        {
            "node_id": "n_plan",
            "node_type": "capability",
            "config": {"capability_key": "vault_search", "inputs": {}},
        },
        {
            "node_id": "n_loop",
            "node_type": "loop",
            "config": {
                "state_schema": {"type": "object"},
                "input_mapping": {"plan": {"$ref": "nodes.n_plan.output"}},
                "continuation_condition": {
                    "from_path": "loop.state.done",
                    "operator": "equals",
                    "value": False,
                },
                "max_iterations": 3,
                "entry_node_id": "n_child",
            },
        },
        {
            "node_id": "n_child",
            "node_type": "capability",
            "config": {"capability_key": "vault_search", "inputs": {}},
            "parent_loop_node_id": "n_loop",
        },
        {
            "node_id": "n_result",
            "node_type": "loop_result",
            "config": {"output_mapping": {"out": {"$ref": "nodes.n_child.output"}}},
            "parent_loop_node_id": "n_loop",
        },
        {"node_id": "n_end", "node_type": "terminal", "config": {"outcome": "success"}},
    ]
    edges = [
        {"edge_id": "e1", "source_node_id": "n_plan", "target_node_id": "n_loop", "order_index": 0},
        {"edge_id": "e2", "source_node_id": "n_loop", "target_node_id": "n_end", "order_index": 0},
        {"edge_id": "e3", "source_node_id": "n_child", "target_node_id": "n_result", "order_index": 0},
    ]
    workflow_store.set_revision_graph(source["revision_id"], nodes, edges)

    draft = workflow_store.create_revision(
        workflow["workflow_id"], source_revision_id=source["revision_id"]
    )
    new_ids = {n["node_id"] for n in draft["nodes"]}
    assert new_ids.isdisjoint({"n_plan", "n_loop", "n_child", "n_result", "n_end"})
    assert len(draft["nodes"]) == len(nodes)
    assert len(draft["edges"]) == len(edges)
    loop = next(n for n in draft["nodes"] if n["node_type"] == "loop")
    child = next(
        n
        for n in draft["nodes"]
        if n["node_type"] == "capability"
        and n["parent_loop_node_id"] == loop["node_id"]
    )
    result = next(n for n in draft["nodes"] if n["node_type"] == "loop_result")
    assert loop["config"]["entry_node_id"] == child["node_id"]
    assert loop["config"]["input_mapping"]["plan"]["$ref"].split(".")[1] in new_ids
    assert result["parent_loop_node_id"] == loop["node_id"]
    assert result["config"]["output_mapping"]["out"]["$ref"].split(".")[1] == child["node_id"]
    assert {e["source_node_id"] for e in draft["edges"]} <= new_ids
    assert {e["target_node_id"] for e in draft["edges"]} <= new_ids

    # The source revision keeps its original ids and references.
    stored = workflow_store.get_revision(source["revision_id"])
    assert {n["node_id"] for n in stored["nodes"]} == {
        "n_plan",
        "n_loop",
        "n_child",
        "n_result",
        "n_end",
    }
    stored_loop = next(n for n in stored["nodes"] if n["node_type"] == "loop")
    assert stored_loop["config"]["entry_node_id"] == "n_child"


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


def test_workflow_capabilities_and_new_revision(test_memory_db_path, client):
    task_store.sync_capabilities()
    caps = client.get("/api/v1/workflows/capabilities")
    assert caps.status_code == 200
    items = caps.json()["items"]
    keys = {c["capability_key"] for c in items}
    assert "hitl_wait" in keys
    hitl = next(c for c in items if c["capability_key"] == "hitl_wait")
    assert hitl["workflow_only"] is True
    assert hitl["approval_policy"] == "auto"

    # Capability input schemas are exposed for the guided editor.
    assert hitl["inputs_schema"]["properties"]["question"]["type"] == "string"
    vault = next(c for c in items if c["capability_key"] == "vault_write_file")
    assert set(vault["inputs_schema"]["properties"]) >= {
        "relative_path",
        "content",
    }

    created = client.post("/api/v1/workflows", json={"name": "rev"})
    workflow_id = created.json()["workflow_id"]
    # No published revision yet: the new draft starts blank.
    second = client.post(f"/api/v1/workflows/{workflow_id}/revisions")
    assert second.status_code == 201
    assert second.json()["version"] == 2
    assert second.json()["status"] == "draft"
    assert second.json()["nodes"] == []
    assert second.json()["edges"] == []


def _publishable_graph():
    inputs_schema = {
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
    }
    nodes = [
        {
            "node_id": "n_a",
            "node_type": "capability",
            "config": {
                "capability_key": "vault_search",
                "inputs": {"query": {"$ref": "run.inputs.topic"}},
            },
            "ui_position": {"x": 120, "y": 80},
        },
        {"node_id": "n_end", "node_type": "terminal", "config": {"outcome": "success"}},
    ]
    edges = [
        {
            "edge_id": "e1",
            "source_node_id": "n_a",
            "target_node_id": "n_end",
            "order_index": 0,
        }
    ]
    return inputs_schema, nodes, edges


def test_new_draft_clones_published_revision(test_memory_db_path, client):
    task_store.sync_capabilities()
    created = client.post("/api/v1/workflows", json={"name": "clone"})
    workflow_id = created.json()["workflow_id"]
    revision_id = created.json()["revision"]["revision_id"]
    inputs_schema, nodes, edges = _publishable_graph()
    client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": inputs_schema, "nodes": nodes, "edges": edges},
    )
    assert client.post(
        f"/api/v1/workflows/revisions/{revision_id}/publish"
    ).status_code == 200
    original = client.get(f"/api/v1/workflows/revisions/{revision_id}").json()

    draft = client.post(f"/api/v1/workflows/{workflow_id}/revisions").json()
    assert draft["status"] == "draft"
    assert draft["version"] == 2
    assert draft["inputs_schema"] == original["inputs_schema"]
    assert len(draft["nodes"]) == len(original["nodes"])
    assert len(draft["edges"]) == len(original["edges"])
    original_ids = {n["node_id"] for n in original["nodes"]}
    draft_ids = {n["node_id"] for n in draft["nodes"]}
    assert original_ids.isdisjoint(draft_ids)
    # Typed references and layout survive the copy.
    cloned_cap = next(n for n in draft["nodes"] if n["node_type"] == "capability")
    assert cloned_cap["config"]["inputs"]["query"] == {"$ref": "run.inputs.topic"}
    assert cloned_cap["ui_position"] == {"x": 120, "y": 80}
    # Edge endpoints point at the copied nodes.
    assert draft["edges"][0]["source_node_id"] in draft_ids
    assert draft["edges"][0]["target_node_id"] in draft_ids
    # The cloned draft is independently valid and publishable.
    assert client.post(
        f"/api/v1/workflows/revisions/{draft['revision_id']}/validate"
    ).json()["valid"] is True

    # The source published revision is unchanged.
    after = client.get(f"/api/v1/workflows/revisions/{revision_id}").json()
    assert after["status"] == "published"
    assert {n["node_id"] for n in after["nodes"]} == original_ids
    assert after["nodes"] == original["nodes"]


def test_editing_cloned_draft_does_not_affect_source(test_memory_db_path, client):
    task_store.sync_capabilities()
    created = client.post("/api/v1/workflows", json={"name": "isolate"})
    workflow_id = created.json()["workflow_id"]
    revision_id = created.json()["revision"]["revision_id"]
    inputs_schema, nodes, edges = _publishable_graph()
    client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": inputs_schema, "nodes": nodes, "edges": edges},
    )
    client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")

    draft = client.post(f"/api/v1/workflows/{workflow_id}/revisions").json()
    # Replace the draft graph entirely.
    client.put(
        f"/api/v1/workflows/revisions/{draft['revision_id']}",
        json={"inputs_schema": {"type": "object"}, "nodes": [], "edges": []},
    )
    after = client.get(f"/api/v1/workflows/revisions/{revision_id}").json()
    assert [n["node_id"] for n in after["nodes"]] == ["n_a", "n_end"]
    assert after["nodes"][0]["config"] == nodes[0]["config"]
    assert after["edges"][0]["edge_id"] == "e1"
    assert after["status"] == "published"


def test_templates_and_instantiation_use_fresh_ids(test_memory_db_path, client):
    templates = client.get("/api/v1/workflows/templates")
    assert templates.status_code == 200
    keys = {t["template_key"] for t in templates.json()["items"]}
    assert "plan_review_execute" in keys
    assert "contextual_research" in keys

    first = client.post(
        "/api/v1/workflows/from-template",
        json={"template_key": "contextual_research"},
    )
    assert first.status_code == 201
    first_revision = first.json()["revision"]
    assert len(first_revision["nodes"]) == 4
    assert len(first_revision["edges"]) == 3
    # References point at freshly generated node ids, not template symbols.
    node_ids = {n["node_id"] for n in first_revision["nodes"]}
    assert all(nid not in {"context", "theme", "research", "done"} for nid in node_ids)

    second = client.post(
        "/api/v1/workflows/from-template",
        json={"template_key": "contextual_research"},
    )
    second_ids = {n["node_id"] for n in second.json()["revision"]["nodes"]}
    assert node_ids.isdisjoint(second_ids)


def test_list_events_after(test_memory_db_path):
    workflow = workflow_store.create_workflow("events")
    workflow_store.publish_revision(workflow["revision"]["revision_id"])
    run = workflow_store.create_run(
        workflow["workflow_id"], workflow["revision"]["revision_id"], {}
    )
    workflow_store.append_event(run["run_id"], "node_started", {"n": 1})
    workflow_store.append_event(run["run_id"], "node_completed", {"n": 2})
    after_first = workflow_store.list_events_after(run["run_id"], 1)
    assert [event["event_type"] for event in after_first] == ["node_completed"]
    assert workflow_store.list_events_after(run["run_id"], 2) == []


def test_template_references_are_remapped(test_memory_db_path, client):
    created = client.post(
        "/api/v1/workflows/from-template",
        json={"template_key": "plan_review_execute"},
    ).json()
    revision = created["revision"]
    node_ids = {n["node_id"] for n in revision["nodes"]}
    loop = next(n for n in revision["nodes"] if n["node_type"] == "loop")
    child_ids = {
        n["node_id"] for n in revision["nodes"] if n["parent_loop_node_id"] == loop["node_id"]
    }
    assert loop["config"]["entry_node_id"] in child_ids
    assert loop["config"]["input_mapping"]["plan"]["$ref"].startswith("nodes.")
    referenced = loop["config"]["input_mapping"]["plan"]["$ref"].split(".")[1]
    assert referenced in node_ids

    result = next(n for n in revision["nodes"] if n["node_type"] == "loop_result")
    for mapping in result["config"]["output_mapping"].values():
        assert mapping["$ref"].split(".")[1] in node_ids
    # Every instantiated node carries a canvas position.
    assert all(n["ui_position"] is not None for n in revision["nodes"])


def _terminal_run(client, revision_id, inputs):
    run = client.post(
        f"/api/v1/workflows/revisions/{revision_id}/runs", json={"inputs": inputs}
    ).json()
    workflow_store.claim_run("rerun-test")
    workflow_store.transition_run_status(run["run_id"], "completed")
    return run


def test_rerun_from_snapshot_with_input_override(test_memory_db_path, client):
    created = client.post(
        "/api/v1/workflows",
        json={
            "name": "rerun",
            "inputs_schema": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        },
    )
    revision_id = created.json()["revision"]["revision_id"]
    nodes = [
        {
            "node_id": "n_a",
            "node_type": "capability",
            "config": {"capability_key": "research_context_snapshot", "inputs": {}},
        },
        {"node_id": "n_end", "node_type": "terminal", "config": {"outcome": "success"}},
    ]
    edges = [
        {
            "edge_id": "e1",
            "source_node_id": "n_a",
            "target_node_id": "n_end",
            "order_index": 0,
        }
    ]
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
    source = _terminal_run(client, revision_id, {"topic": "first"})

    # A non-terminal run cannot be rerun.
    queued = client.post(
        f"/api/v1/workflows/revisions/{revision_id}/runs", json={"inputs": {"topic": "x"}}
    ).json()
    assert client.post(f"/api/v1/workflows/runs/{queued['run_id']}/rerun", json={}).status_code == 409

    # Supersede the source revision; rerun must still work from the snapshot.
    second = client.post(f"/api/v1/workflows/{created.json()['workflow_id']}/revisions").json()
    client.put(
        f"/api/v1/workflows/revisions/{second['revision_id']}",
        json={
            "inputs_schema": {"type": "object"},
            "nodes": nodes,
            "edges": edges,
        },
    )
    client.post(f"/api/v1/workflows/revisions/{second['revision_id']}/publish")

    rerun = client.post(
        f"/api/v1/workflows/runs/{source['run_id']}/rerun",
        json={"inputs": {"topic": "second"}},
    )
    assert rerun.status_code == 201
    body = rerun.json()
    assert body["status"] == "queued"
    assert body["inputs"] == {"topic": "second"}
    assert body["source_run_id"] == source["run_id"]
    assert body["revision_id"] == revision_id
    assert len(body["graph_snapshot"]["nodes"]) == 2

    # Input override is validated against the snapshot schema.
    bad = client.post(
        f"/api/v1/workflows/runs/{source['run_id']}/rerun", json={"inputs": {}}
    )
    assert bad.status_code == 422


def test_rerun_without_inputs_copies_source_inputs(test_memory_db_path, client):
    created = client.post("/api/v1/workflows", json={"name": "rerun-copy"})
    revision_id = created.json()["revision"]["revision_id"]
    nodes = [
        {
            "node_id": "n_a",
            "node_type": "capability",
            "config": {"capability_key": "research_context_snapshot", "inputs": {}},
        },
        {"node_id": "n_end", "node_type": "terminal", "config": {"outcome": "success"}},
    ]
    edges = [
        {"edge_id": "e1", "source_node_id": "n_a", "target_node_id": "n_end", "order_index": 0}
    ]
    client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": {"type": "object"}, "nodes": nodes, "edges": edges},
    )
    client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")
    source = _terminal_run(client, revision_id, {"k": "v"})
    rerun = client.post(f"/api/v1/workflows/runs/{source['run_id']}/rerun", json={}).json()
    assert rerun["inputs"] == {"k": "v"}


def test_rerun_recomputes_approval_from_snapshot(test_memory_db_path, client):
    task_store.sync_capabilities()
    created = client.post("/api/v1/workflows", json={"name": "rerun-approval"})
    revision_id = created.json()["revision"]["revision_id"]
    nodes = [
        {
            "node_id": "n_write",
            "node_type": "capability",
            "config": {
                "capability_key": "vault_write_file",
                "inputs": {"relative_path": "x.md", "content": "hi", "overwrite": True},
            },
        },
        {"node_id": "n_end", "node_type": "terminal", "config": {"outcome": "success"}},
    ]
    edges = [
        {"edge_id": "e1", "source_node_id": "n_write", "target_node_id": "n_end", "order_index": 0}
    ]
    client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": {"type": "object"}, "nodes": nodes, "edges": edges},
    )
    client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")
    source = client.post(
        f"/api/v1/workflows/revisions/{revision_id}/runs", json={"inputs": {}}
    ).json()
    assert source["status"] == "waiting_approval"
    client.post(f"/api/v1/workflows/runs/{source['run_id']}/approve")
    workflow_store.claim_run("rerun-approval-test")
    workflow_store.transition_run_status(source["run_id"], "completed")

    rerun = client.post(f"/api/v1/workflows/runs/{source['run_id']}/rerun", json={}).json()
    # A plan_required capability in the snapshot forces approval again.
    assert rerun["status"] == "waiting_approval"


def _graph_counts(revision_id):
    from obsidian_ai_hub.database import get_db_connection

    with get_db_connection() as conn:
        nodes = conn.execute(
            "SELECT COUNT(*) AS n FROM workflow_nodes WHERE revision_id = ?;",
            (revision_id,),
        ).fetchone()["n"]
        edges = conn.execute(
            "SELECT COUNT(*) AS n FROM workflow_edges WHERE revision_id = ?;",
            (revision_id,),
        ).fetchone()["n"]
    return int(nodes), int(edges)


def test_delete_superseded_revision_keeps_run_and_allows_rerun(
    test_memory_db_path, client
):
    """Operation scenario: delete a superseded revision end to end.

    Old revision's graph disappears, the referencing run survives, and a
    rerun still works from the run's own graph snapshot.
    """
    created = client.post("/api/v1/workflows", json={"name": "rev-delete"}).json()
    workflow_id = created["workflow_id"]
    old_revision_id = created["revision"]["revision_id"]
    nodes, edges = _linear_graph()
    client.put(
        f"/api/v1/workflows/revisions/{old_revision_id}",
        json={"inputs_schema": {"type": "object"}, "nodes": nodes, "edges": edges},
    )
    client.post(f"/api/v1/workflows/revisions/{old_revision_id}/publish")
    source = _terminal_run(client, old_revision_id, {})

    # Supersede the old revision by publishing a new draft, then delete it.
    draft = client.post(f"/api/v1/workflows/{workflow_id}/revisions").json()
    republished = client.post(
        f"/api/v1/workflows/revisions/{draft['revision_id']}/publish"
    )
    assert republished.status_code == 200
    deleted = client.delete(f"/api/v1/workflows/revisions/{old_revision_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"success": True, "revision_id": old_revision_id}

    assert (
        client.get(f"/api/v1/workflows/revisions/{old_revision_id}").status_code
        == 404
    )
    assert _graph_counts(old_revision_id) == (0, 0)

    # The run survives with its dangling revision_id, and rerun works.
    assert (
        client.get(f"/api/v1/workflows/runs/{source['run_id']}").status_code == 200
    )
    rerun = client.post(
        f"/api/v1/workflows/runs/{source['run_id']}/rerun", json={}
    )
    assert rerun.status_code == 201
    assert rerun.json()["source_run_id"] == source["run_id"]
    assert rerun.json()["revision_id"] == old_revision_id

    # The new draft is untouched.
    assert (
        client.get(f"/api/v1/workflows/revisions/{draft['revision_id']}").status_code
        == 200
    )


def test_delete_draft_revision(test_memory_db_path, client):
    created = client.post("/api/v1/workflows", json={"name": "draft-delete"}).json()
    revision_id = created["revision"]["revision_id"]
    nodes, edges = _linear_graph()
    client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": {"type": "object"}, "nodes": nodes, "edges": edges},
    )
    assert _graph_counts(revision_id) == (2, 1)

    assert client.delete(f"/api/v1/workflows/revisions/{revision_id}").status_code == 200
    assert (
        client.get(f"/api/v1/workflows/revisions/{revision_id}").status_code == 404
    )
    assert _graph_counts(revision_id) == (0, 0)

    # The workflow survives with no revisions; a fresh draft can be created.
    detail = client.get(f"/api/v1/workflows/{created['workflow_id']}").json()
    assert detail["revisions"] == []
    new_draft = client.post(
        f"/api/v1/workflows/{created['workflow_id']}/revisions"
    ).json()
    assert new_draft["status"] == "draft"


def test_delete_published_or_missing_revision_fails_without_side_effects(
    test_memory_db_path, client
):
    created = client.post("/api/v1/workflows", json={"name": "rev-guard"}).json()
    revision_id = created["revision"]["revision_id"]
    nodes, edges = _linear_graph()
    client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": {"type": "object"}, "nodes": nodes, "edges": edges},
    )
    client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")

    assert (
        client.delete(f"/api/v1/workflows/revisions/{revision_id}").status_code
        == 409
    )
    assert (
        client.delete("/api/v1/workflows/revisions/wrev_does_not_exist").status_code
        == 404
    )

    # The published revision and its graph are untouched.
    assert (
        client.get(f"/api/v1/workflows/revisions/{revision_id}").status_code == 200
    )
    assert _graph_counts(revision_id) == (2, 1)
