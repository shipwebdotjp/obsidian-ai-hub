"""Cancellation is a request, not a rollback.

Operation-scenario contract for this module (see
``docs/development-quality-playbook.md`` and
``docs/workflow/adr/workflow-graph-and-agent-node.md``):

- Cancelling before the bridge Task is saved must not start the external
  operation and must end Node/Run as ``cancelled``.
- A cooperative child cancel ends Node/Run as ``cancelled``.
- An external process that completed or whose outcome is unknown must stop at
  ``needs_attention`` / ``waiting_attention`` instead of continuing.
- Adopting a cancel-origin attention Node requires stored success evidence;
  without it the API refuses with 409.
- Cancelling a ``waiting_hitl`` Run cancels the linked HITL Run.
- Cancelling inside a Loop does not start the next iteration.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.hitl import store as hitl_store
from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.execution import (
    CANCEL_CERTAINTY_CANCELLED,
    CANCEL_CERTAINTY_COMPLETED,
    CANCEL_CERTAINTY_UNKNOWN,
    CancellationEvidence,
    TaskCancelled,
)
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.execution import (
    ATTENTION_REASON_CANCEL_COMPLETED,
    ATTENTION_REASON_CANCEL_UNKNOWN,
    NodeOutcome,
    WorkflowEngine,
)
from obsidian_ai_hub.workflow.runners import DefaultNodeRunner


@pytest.fixture
def client(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


def _node(node_id, node_type, config, parent=None):
    return {
        "node_id": node_id,
        "node_type": node_type,
        "config": config,
        "parent_loop_node_id": parent,
    }


def _edge(edge_id, source, target, *, condition=None, order=0, kind="normal"):
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_kind": kind,
        "condition": condition,
        "order_index": order,
    }


def _published_run(nodes, edges, inputs=None):
    workflow = workflow_store.create_workflow(
        "cancel-test", inputs_schema={"type": "object"}
    )
    revision = workflow["revision"]
    workflow_store.set_revision_graph(revision["revision_id"], nodes, edges)
    workflow_store.publish_revision(revision["revision_id"])
    return workflow_store.create_run(
        workflow["workflow_id"], revision["revision_id"], inputs or {}
    )


def _claim(run_id):
    claimed = workflow_store.claim_run("test-instance")
    assert claimed is not None
    assert claimed["run_id"] == run_id
    return claimed


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute_step(self, task, plan, step_index, step):
        self.calls += 1
        raise AssertionError("external operation must not start")


class _FakeRunner:
    def __init__(self, handler):
        self.handler = handler
        self.calls = 0

    def run(self, *, node, inputs, context):
        self.calls += 1
        return self.handler(node, inputs, context)


def _linear_graph():
    return (
        [
            _node("a", "capability", {"capability_key": "vault_search", "inputs": {}}),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [_edge("e1", "a", "t")],
    )


# --- cancellation before / around the external call ------------------------


def test_cancel_before_node_does_not_start_runner():
    run = _published_run(*_linear_graph())
    _claim(run["run_id"])
    workflow_store.request_run_cancel(run["run_id"])
    assert workflow_store.get_run(run["run_id"])["status"] == "cancelling"

    runner = _FakeRunner(lambda n, i, c: _unexpected())
    outcome = WorkflowEngine(runner).execute(workflow_store.get_run(run["run_id"]))
    assert outcome.kind == "cancelled"
    assert runner.calls == 0
    assert workflow_store.get_run(run["run_id"])["status"] == "cancelled"


def test_cancel_after_bridge_save_skips_external_operation():
    run = _published_run(*_linear_graph())
    _claim(run["run_id"])
    node = {
        "node_id": "a",
        "node_type": "capability",
        "config": {"capability_key": "research_agent"},
    }
    activation_id = workflow_store.get_or_create_activation(run["run_id"], "a", None)
    workflow_store.request_run_cancel(run["run_id"])

    executor = _RecordingExecutor()
    runner = DefaultNodeRunner()
    runner._executor = executor
    outcome = runner.run(
        node=node,
        inputs={"theme": "x"},
        context={
            "run_id": run["run_id"],
            "node_id": "a",
            "activation_id": activation_id,
            "attempt": 1,
        },
    )
    assert outcome.status == "cancelled"
    assert outcome.result_certainty == CANCEL_CERTAINTY_CANCELLED
    assert executor.calls == 0
    bridge_tasks = [
        t
        for t in task_store.list_tasks()
        if run["run_id"] in str(t.get("prompt_text") or "")
    ]
    assert len(bridge_tasks) == 1
    assert bridge_tasks[0]["status"] == "cancelled"


def _unexpected():
    raise AssertionError("runner must not be called")


# --- cancelled versus waiting_attention ------------------------------------


def test_cooperative_child_cancel_cancels_node_and_run():
    run = _published_run(*_linear_graph())
    _claim(run["run_id"])
    run_id = run["run_id"]

    def handler(node, inputs, context):
        # A concurrent cancel request moves the run to ``cancelling`` while
        # the child cooperates and reports a confirmed cancellation.
        workflow_store.request_run_cancel(run_id)
        return NodeOutcome(
            status="cancelled", result_certainty=CANCEL_CERTAINTY_CANCELLED
        )

    engine = WorkflowEngine(_FakeRunner(handler))
    outcome = engine.execute(workflow_store.get_run(run_id))
    assert outcome.kind == "cancelled"
    assert workflow_store.get_run(run["run_id"])["status"] == "cancelled"
    node = workflow_store.list_run_nodes(run["run_id"])[0]
    assert node["status"] == "cancelled"


def test_completed_external_result_requires_attention():
    run = _published_run(*_linear_graph())
    _claim(run["run_id"])
    engine = WorkflowEngine(
        _FakeRunner(
            lambda n, i, c: NodeOutcome(
                status="cancelled",
                result_certainty=CANCEL_CERTAINTY_COMPLETED,
                output={"summary": "done"},
                child_kind="research",
                child_run_id="job1",
                satisfied_effects=("research_saved",),
            )
        )
    )
    outcome = engine.execute(workflow_store.get_run(run["run_id"]))
    assert outcome.kind == "waiting_attention"
    assert workflow_store.get_run(run["run_id"])["status"] == "waiting_attention"
    node = workflow_store.list_run_nodes(run["run_id"])[0]
    assert node["status"] == "needs_attention"
    assert node["attention_reason"] == ATTENTION_REASON_CANCEL_COMPLETED
    assert node["output"] == {"summary": "done"}
    assert node["effects"] == ["research_saved"]


def test_unknown_external_result_requires_attention():
    run = _published_run(*_linear_graph())
    _claim(run["run_id"])
    engine = WorkflowEngine(
        _FakeRunner(
            lambda n, i, c: NodeOutcome(
                status="cancelled",
                result_certainty=CANCEL_CERTAINTY_UNKNOWN,
                child_kind="agent",
                child_run_id="run1",
            )
        )
    )
    outcome = engine.execute(workflow_store.get_run(run["run_id"]))
    assert outcome.kind == "waiting_attention"
    node = workflow_store.list_run_nodes(run["run_id"])[0]
    assert node["attention_reason"] == ATTENTION_REASON_CANCEL_UNKNOWN
    assert node["cancel_outcome"] == CANCEL_CERTAINTY_UNKNOWN


def test_adapter_cancel_evidence_propagates_to_node():
    """A TaskCancelled from the executor becomes a reviewable attention node."""
    run = _published_run(*_linear_graph())
    _claim(run["run_id"])
    activation_id = workflow_store.get_or_create_activation(run["run_id"], "a", None)

    class _CancellingExecutor:
        def execute_step(self, task, plan, step_index, step):
            raise TaskCancelled(
                "cancelled",
                evidence=CancellationEvidence(
                    child_kind="research",
                    child_run_id="job9",
                    result_certainty=CANCEL_CERTAINTY_COMPLETED,
                    result_summary="[title] t\n\nbody",
                ),
            )

    node = {
        "node_id": "a",
        "node_type": "capability",
        "config": {"capability_key": "research_agent"},
    }
    runner = DefaultNodeRunner()
    runner._executor = _CancellingExecutor()
    outcome = runner.run(
        node=node,
        inputs={"theme": "x"},
        context={
            "run_id": run["run_id"],
            "node_id": "a",
            "activation_id": activation_id,
            "attempt": 1,
        },
    )
    assert outcome.status == "cancelled"
    assert outcome.child_kind == "research"
    assert outcome.child_run_id == "job9"
    assert outcome.result_certainty == CANCEL_CERTAINTY_COMPLETED
    # A recovered result is preserved so the cancel-origin node is adoptable.
    assert outcome.output == {"summary": "[title] t\n\nbody"}


# --- attention adoption ----------------------------------------------------


def _attention_run(client, *, evidence: bool):
    task_store.sync_capabilities()
    created = client.post("/api/v1/workflows", json={"name": "adopt"})
    revision_id = created.json()["revision"]["revision_id"]
    nodes, edges = _linear_graph()
    client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": {"type": "object"}, "nodes": nodes, "edges": edges},
    )
    client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")
    run = client.post(
        f"/api/v1/workflows/revisions/{revision_id}/runs", json={"inputs": {}}
    ).json()
    run_id = run["run_id"]
    _claim(run_id)
    activation_id = workflow_store.get_or_create_activation(run_id, "a", None)
    workflow_store.upsert_run_node(
        run_id=run_id,
        node_id="a",
        activation_id=activation_id,
        attempt=1,
        status="needs_attention",
        output={"summary": "adoptable"} if evidence else None,
        effects=("research_saved",) if evidence else None,
        child_kind="research",
        child_run_id="job1",
        cancel_outcome=(
            CANCEL_CERTAINTY_COMPLETED if evidence else CANCEL_CERTAINTY_UNKNOWN
        ),
        attention_reason=(
            ATTENTION_REASON_CANCEL_COMPLETED
            if evidence
            else ATTENTION_REASON_CANCEL_UNKNOWN
        ),
    )
    workflow_store.transition_run_status(run_id, "waiting_attention")
    return run_id


def test_adopt_with_evidence_keeps_output_and_does_not_rerun(client):
    run_id = _attention_run(client, evidence=True)
    response = client.post(
        f"/api/v1/workflows/runs/{run_id}/attention", json={"decision": "adopt"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"

    _claim(run_id)
    outcome = WorkflowEngine(_FakeRunner(lambda n, i, c: _unexpected())).execute(
        workflow_store.get_run(run_id)
    )
    assert outcome.kind == "completed"
    node = workflow_store.list_run_nodes(run_id)[0]
    assert node["status"] == "succeeded"
    assert node["output"] == {"summary": "adoptable"}


def test_adopt_without_evidence_is_rejected(client):
    run_id = _attention_run(client, evidence=False)
    response = client.post(
        f"/api/v1/workflows/runs/{run_id}/attention", json={"decision": "adopt"}
    )
    assert response.status_code == 409
    assert workflow_store.get_run(run_id)["status"] == "waiting_attention"
    node = workflow_store.list_run_nodes(run_id)[0]
    assert node["status"] == "needs_attention"


# --- HITL cancellation -----------------------------------------------------


def test_cancel_waiting_hitl_cancels_linked_hitl_run(client):
    nodes = [
        _node("h", "capability", {"capability_key": "hitl_wait", "inputs": {}}),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    run = _published_run(nodes, [_edge("e1", "h", "t")])
    _claim(run["run_id"])
    outcome = WorkflowEngine(DefaultNodeRunner()).execute(
        workflow_store.get_run(run["run_id"])
    )
    assert outcome.kind == "waiting_hitl"
    node = workflow_store.list_run_nodes(run["run_id"])[0]
    hitl_run_id = node["hitl_run_id"]
    assert hitl_run_id
    assert hitl_store.get_run(hitl_run_id)["status"] == "pending_user"

    response = client.post(f"/api/v1/workflows/runs/{run['run_id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert hitl_store.get_run(hitl_run_id)["status"] == "cancelled"


def test_cancel_arriving_while_parking_hitl_stops_cancelled():
    """A cancel that lands as a HITL node parks must not raise / fail the run."""
    run = _published_run(*_linear_graph())
    _claim(run["run_id"])
    run_id = run["run_id"]

    def handler(node, inputs, context):
        workflow_store.request_run_cancel(run_id)
        return NodeOutcome(status="waiting_hitl", hitl_run_id="whitl_missing")

    outcome = WorkflowEngine(_FakeRunner(handler)).execute(
        workflow_store.get_run(run_id)
    )
    assert outcome.kind == "cancelled"
    assert workflow_store.get_run(run_id)["status"] == "cancelled"


# --- loop cancellation -----------------------------------------------------


def test_cancel_in_loop_does_not_start_next_iteration():
    loop = _node(
        "loop",
        "loop",
        {
            "state_schema": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "done": {"type": "boolean"},
                },
            },
            "input_mapping": {"count": 0, "done": False},
            "continuation_condition": {
                "from_path": "loop.state.done",
                "operator": "equals",
                "value": False,
            },
            "max_iterations": 5,
            "entry_node_id": "step",
        },
    )
    step = _node(
        "step",
        "capability",
        {"capability_key": "vault_search", "inputs": {}},
        parent="loop",
    )
    result = _node(
        "result",
        "loop_result",
        {"output_mapping": {"count": {"$ref": "nodes.step.output.count"}}},
        parent="loop",
    )
    terminal = _node("t", "terminal", {"outcome": "success"})
    run = _published_run(
        [loop, step, result, terminal],
        [_edge("e1", "loop", "t"), _edge("e2", "step", "result")],
    )
    _claim(run["run_id"])
    run_id = run["run_id"]

    def handler(node, inputs, context):
        workflow_store.request_run_cancel(run_id)
        return NodeOutcome(status="succeeded", output={"count": 1})

    runner = _FakeRunner(handler)
    outcome = WorkflowEngine(runner).execute(workflow_store.get_run(run_id))
    assert outcome.kind == "cancelled"
    assert runner.calls == 1
    assert workflow_store.get_run(run_id)["status"] == "cancelled"
    events = workflow_store.list_events(run_id)
    started = [
        e for e in events if e["event_type"] == "loop_iteration_started"
    ]
    assert len(started) == 1
