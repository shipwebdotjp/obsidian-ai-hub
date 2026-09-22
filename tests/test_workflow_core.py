"""Unit tests for workflow models and static validation."""

from __future__ import annotations

from obsidian_ai_hub.workflow.models import (
    evaluate_condition,
    resolve_reference,
    validate_schema_subset,
    validate_value_against_schema,
)
from obsidian_ai_hub.workflow.validation import validate_graph


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


# --- models -----------------------------------------------------------------


def test_schema_subset_rejects_ref_and_unknown_keys():
    assert validate_schema_subset({"$ref": "#/x"}) != []
    assert validate_schema_subset({"type": "object", "properties": {}}) == []
    assert validate_schema_subset({"type": "object", "properties": {"a": {"type": "string", "unknown": 1}}}) != []
    assert validate_schema_subset(
        {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    ) == []


def test_schema_subset_requires_items_for_array():
    assert validate_schema_subset({"type": "array"}) != []


def test_value_validation_respects_required_and_types():
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
    }
    assert validate_value_against_schema({}, schema)
    assert validate_value_against_schema({"n": True}, schema)
    assert validate_value_against_schema({"n": 3}, schema) == []


def test_resolve_reference_paths():
    value = resolve_reference(
        "nodes.n1.output.items[0].path",
        run_inputs={"title": "t"},
        node_outputs={"n1": {"items": [{"path": "/a"}]}},
    )
    assert value == "/a"
    assert (
        resolve_reference(
            "run.inputs.title", run_inputs={"title": "t"}, node_outputs={}
        )
        == "t"
    )


def test_condition_evaluation():
    state = {"done": False, "kind": "a"}
    assert (
        evaluate_condition(
            {"from_path": "loop.state.done", "operator": "equals", "value": False},
            lambda p: state["done"],
        )
        is True
    )
    assert (
        evaluate_condition(
            {"from_path": "loop.state.kind", "operator": "in", "value": ["a", "b"]},
            lambda p: state["kind"],
        )
        is True
    )


# --- validation -------------------------------------------------------------


def test_valid_linear_graph():
    nodes = [
        _node("a", "capability", {"capability_key": "vault_search", "inputs": {}}),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t")]
    assert validate_graph(nodes=nodes, edges=edges) == []


def test_cycle_is_rejected():
    nodes = [
        _node("a", "capability", {"capability_key": "vault_search", "inputs": {}}),
        _node("b", "capability", {"capability_key": "vault_search", "inputs": {}}),
    ]
    edges = [_edge("e1", "a", "b"), _edge("e2", "b", "a")]
    errors = validate_graph(nodes=nodes, edges=edges)
    assert any(e.startswith("cycle:") for e in errors)


def test_two_entries_rejected():
    nodes = [
        _node("a", "capability", {"capability_key": "vault_search", "inputs": {}}),
        _node("b", "capability", {"capability_key": "vault_search", "inputs": {}}),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t"), _edge("e2", "b", "t")]
    errors = validate_graph(nodes=nodes, edges=edges)
    assert any(e.startswith("entry_count:") for e in errors)


def test_unknown_reference_scope_is_rejected():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {"q": {"$ref": "nodes.missing.output.x"}},
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t")]
    errors = validate_graph(nodes=nodes, edges=edges)
    assert any(e.startswith("reference_scope:") for e in errors)


def test_loop_requires_loop_result():
    loop = _node(
        "loop",
        "loop",
        {
            "state_schema": {"type": "object", "properties": {"n": {"type": "integer"}}},
            "input_mapping": {"n": 0},
            "continuation_condition": {
                "from_path": "loop.state.n",
                "operator": "equals",
                "value": 0,
            },
            "max_iterations": 3,
            "entry_node_id": "child",
        },
    )
    child = _node(
        "child",
        "capability",
        {"capability_key": "vault_search", "inputs": {}},
        parent="loop",
    )
    terminal = _node("t", "terminal", {"outcome": "success"})
    errors = validate_graph(
        nodes=[loop, child, terminal], edges=[_edge("e1", "loop", "t")]
    )
    assert any(e.startswith("loop_result_count:") for e in errors)


def test_nested_loop_rejected():
    outer = _node(
        "outer",
        "loop",
        {
            "state_schema": {"type": "object"},
            "input_mapping": {},
            "continuation_condition": {
                "from_path": "loop.state.x",
                "operator": "exists",
            },
            "max_iterations": 2,
            "entry_node_id": "inner",
        },
    )
    inner = _node(
        "inner",
        "loop",
        {
            "state_schema": {"type": "object"},
            "input_mapping": {},
            "continuation_condition": {
                "from_path": "loop.state.x",
                "operator": "exists",
            },
            "max_iterations": 2,
            "entry_node_id": "lr",
        },
        parent="outer",
    )
    lr = _node("lr", "loop_result", {"output_mapping": {}}, parent="outer")
    terminal = _node("t", "terminal", {"outcome": "success"})
    errors = validate_graph(
        nodes=[outer, inner, lr, terminal], edges=[_edge("e1", "outer", "t")]
    )
    assert any(e.startswith("loop_nested:") for e in errors)


def test_indexed_run_input_reference_is_valid():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {"q": {"$ref": "run.inputs.items[0]"}},
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t")]
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "string"}}},
    }
    assert validate_graph(nodes=nodes, edges=edges, inputs_schema=schema) == []


def test_target_capability_requires_and_validates_target():
    terminal = _node("t", "terminal", {"outcome": "success"})
    edges = [_edge("e1", "a", "t")]

    missing = _node(
        "a",
        "capability",
        {"capability_key": "specialist_agent", "inputs": {"task": "x"}},
    )
    errors = validate_graph(nodes=[missing, terminal], edges=edges)
    assert any("target が必要です" in e for e in errors)

    valid = _node(
        "a",
        "capability",
        {
            "capability_key": "specialist_agent",
            "inputs": {"task": "x"},
            "target": {"agent_id": "agent_1"},
        },
    )
    assert validate_graph(nodes=[valid, terminal], edges=edges) == []

    invalid = _node(
        "a",
        "capability",
        {"capability_key": "coding_cli", "inputs": {}, "target": {"project_id": "x"}},
    )
    errors = validate_graph(nodes=[invalid, terminal], edges=edges)
    assert any("target が不正です" in e for e in errors)


def test_workflow_catalog_includes_hitl_wait_without_task_agent():
    from obsidian_ai_hub.tasks.capabilities import get_capability_keys
    from obsidian_ai_hub.workflow.capabilities import (
        default_approval_policy,
        is_workflow_only,
        workflow_capability_keys,
    )

    keys = workflow_capability_keys()
    assert "hitl_wait" in keys
    assert "hitl_wait" not in get_capability_keys()
    assert is_workflow_only("hitl_wait") is True
    assert default_approval_policy("hitl_wait") == "auto"
