"""Execution-engine tests with a fake NodeRunner (no external services)."""

from __future__ import annotations

from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.execution import NodeOutcome, WorkflowEngine


class FakeRunner:
    def __init__(self, handler):
        self.handler = handler

    def run(self, *, node, inputs, context):
        return self.handler(node, inputs, context)


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


def _setup(nodes, edges, inputs=None, inputs_schema=None):
    workflow = workflow_store.create_workflow(
        "test", inputs_schema=inputs_schema or {"type": "object"}
    )
    revision = workflow["revision"]
    workflow_store.set_revision_graph(revision["revision_id"], nodes, edges)
    workflow_store.publish_revision(revision["revision_id"])
    workflow_store.create_run(
        workflow["workflow_id"], revision["revision_id"], inputs or {}
    )
    claimed = workflow_store.claim_run("test-instance")
    assert claimed is not None
    return claimed


def test_linear_success_to_terminal():
    run = _setup(
        [
            _node("a", "capability", {"capability_key": "vault_search", "inputs": {}}),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [_edge("e1", "a", "t")],
    )
    outcome = WorkflowEngine(
        FakeRunner(lambda n, i, c: NodeOutcome(status="succeeded", output={"ok": True}))
    ).execute(run)
    assert outcome.kind == "completed"


def test_declared_effects_must_be_satisfied():
    nodes = [
        _node(
            "a",
            "capability",
            {"capability_key": "research_theme_propose", "inputs": {}},
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t")]

    run = _setup(nodes, edges)
    incomplete = WorkflowEngine(
        FakeRunner(lambda n, i, c: NodeOutcome(status="succeeded", output={}))
    ).execute(run)
    assert incomplete.kind == "incomplete"

    run2 = _setup(
        [
            _node(
                "a2",
                "capability",
                {"capability_key": "research_theme_propose", "inputs": {}},
            ),
            _node("t2", "terminal", {"outcome": "success"}),
        ],
        [_edge("e2", "a2", "t2")],
    )
    completed = WorkflowEngine(
        FakeRunner(
            lambda n, i, c: NodeOutcome(
                status="succeeded",
                output={},
                satisfied_effects=("research_theme_registered",),
            )
        )
    ).execute(run2)
    assert completed.kind == "completed"


def test_forward_conditional_branch():
    nodes = [
        _node("a", "capability", {"capability_key": "vault_search", "inputs": {}}),
        _node("b", "capability", {"capability_key": "vault_read_file", "inputs": {}}),
        _node("c", "capability", {"capability_key": "vault_read_file", "inputs": {}}),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [
        _edge(
            "e1",
            "a",
            "b",
            order=0,
            condition={
                "from_path": "run.inputs.flag",
                "operator": "equals",
                "value": True,
            },
        ),
        _edge("e2", "a", "c", order=1),
        _edge("e3", "b", "t"),
        _edge("e4", "c", "t"),
    ]
    run = _setup(nodes, edges, inputs={"flag": True})
    executed: list[str] = []

    def handler(node, inputs, context):
        executed.append(str(node["node_id"]))
        return NodeOutcome(status="succeeded", output={})

    outcome = WorkflowEngine(FakeRunner(handler)).execute(run)
    assert outcome.kind == "completed"
    assert executed == ["a", "b"]


def test_bounded_loop_runs_until_condition():
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
        {
            "output_mapping": {
                "count": {"$ref": "nodes.step.output.count"},
                "done": {"$ref": "nodes.step.output.done"},
            }
        },
        parent="loop",
    )
    terminal = _node("t", "terminal", {"outcome": "success"})
    run = _setup(
        [loop, step, result, terminal],
        [_edge("e1", "loop", "t"), _edge("e2", "step", "result")],
    )

    def handler(node, inputs, context):
        iteration = context["loop_context"]["iteration"]
        return NodeOutcome(
            status="succeeded",
            output={"count": iteration, "done": iteration >= 2},
        )

    outcome = WorkflowEngine(FakeRunner(handler)).execute(run)
    assert outcome.kind == "completed"
    loop_node = next(
        n for n in workflow_store.list_run_nodes(run["run_id"]) if n["node_id"] == "loop"
    )
    import json

    output = json.loads(loop_node["output_json"])
    assert output["iterations"] == 2
    assert output["exit_reason"] == "condition_satisfied"


def test_hitl_wait_resumes_same_activation():
    run = _setup(
        [
            _node("h", "capability", {"capability_key": "hitl_wait", "inputs": {}}),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [_edge("e1", "h", "t")],
    )
    engine = WorkflowEngine(
        FakeRunner(
            lambda n, i, c: NodeOutcome(status="waiting_hitl", hitl_run_id="h1")
        )
    )
    waiting = engine.execute(run)
    assert waiting.kind == "waiting_hitl"
    assert workflow_store.get_run(run["run_id"])["status"] == "waiting_hitl"

    activation = workflow_store.find_activation(run["run_id"], "h", None)
    assert activation is not None
    workflow_store.append_event(
        run["run_id"],
        "hitl_answer_received",
        {
            "node_id": "h",
            "activation_id": activation["activation_id"],
            "answer": {"approved": True},
        },
    )
    workflow_store.transition_run_status(run["run_id"], "queued")

    # A second engine run must resume from the answer without calling runner.
    def fail_handler(node, inputs, context):
        raise AssertionError("runner must not be called after HITL answer")

    workflow_store.claim_run("test-instance")
    resumed = WorkflowEngine(FakeRunner(fail_handler)).execute(
        workflow_store.get_run(run["run_id"])
    )
    assert resumed.kind == "completed"


def test_needs_attention_can_be_adopted():
    run = _setup(
        [
            _node("a", "capability", {"capability_key": "vault_search", "inputs": {}}),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [_edge("e1", "a", "t")],
    )
    engine = WorkflowEngine(
        FakeRunner(lambda n, i, c: NodeOutcome(status="needs_attention"))
    )
    waiting = engine.execute(run)
    assert waiting.kind == "waiting_attention"

    activation = workflow_store.find_activation(run["run_id"], "a", None)
    assert activation is not None
    workflow_store.append_event(
        run["run_id"],
        "attention_resolved",
        {"node_id": "a", "activation_id": activation["activation_id"], "decision": "adopt"},
    )
    def fail_handler(node, inputs, context):
        raise AssertionError("runner must not rerun after adopt")

    workflow_store.transition_run_status(run["run_id"], "queued")
    workflow_store.claim_run("test-instance")
    resumed = WorkflowEngine(FakeRunner(fail_handler)).execute(
        workflow_store.get_run(run["run_id"])
    )
    assert resumed.kind == "completed"


def test_failure_terminal_marks_failed():
    run = _setup(
        [
            _node("a", "capability", {"capability_key": "vault_search", "inputs": {}}),
            _node("tf", "terminal", {"outcome": "failure"}),
        ],
        [_edge("e1", "a", "tf", kind="error")],
    )
    outcome = WorkflowEngine(
        FakeRunner(lambda n, i, c: NodeOutcome(status="failed", error="boom"))
    ).execute(run)
    assert outcome.kind == "failed"


def test_loop_without_continuation_condition_errors():
    loop = _node(
        "loop",
        "loop",
        {
            "state_schema": {
                "type": "object",
                "properties": {"done": {"type": "boolean"}},
            },
            "input_mapping": {"done": False},
            "max_iterations": 3,
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
        {"output_mapping": {"done": {"$ref": "nodes.step.output.done"}}},
        parent="loop",
    )
    terminal = _node("t", "terminal", {"outcome": "success"})
    run = _setup(
        [loop, step, result, terminal],
        [_edge("e1", "loop", "t"), _edge("e2", "step", "result")],
    )
    engine = WorkflowEngine(
        FakeRunner(lambda n, i, c: NodeOutcome(status="succeeded", output={"done": True}))
    )
    try:
        engine.execute(run)
    except ValueError as exc:
        assert "continuation_condition" in str(exc)
    else:
        raise AssertionError("missing continuation_condition must fail")
