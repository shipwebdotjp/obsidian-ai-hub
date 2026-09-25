"""Unit tests for workflow models and static validation."""

from __future__ import annotations

from obsidian_ai_hub.workflow.models import (
    apply_schema_defaults,
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


def test_schema_subset_accepts_item_count_limits():
    schema = {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
        "maxItems": 5,
    }
    assert validate_schema_subset(schema) == []
    assert validate_schema_subset(
        {"type": "array", "items": {"type": "string"}, "minItems": -1}
    ) != []
    assert validate_schema_subset(
        {"type": "array", "items": {"type": "string"}, "maxItems": True}
    ) != []
    assert validate_schema_subset(
        {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 1,
        }
    ) != []


def test_value_validation_enforces_item_count_limits():
    schema = {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
        "maxItems": 2,
    }
    assert validate_value_against_schema([], schema) != []
    assert validate_value_against_schema(["a"], schema) == []
    assert validate_value_against_schema(["a", "b"], schema) == []
    assert validate_value_against_schema(["a", "b", "c"], schema) != []


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


def test_apply_schema_defaults_fills_missing_object_values():
    schema = {
        "type": "object",
        "properties": {
            "focus": {"type": "string", "default": "all"},
            "ledger_path": {"type": "string", "default": "project/ledger.md"},
            "nested": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 5}},
            },
        },
        "required": ["focus"],
    }
    empty: dict = {}
    filled = apply_schema_defaults(empty, schema)
    assert filled == {
        "focus": "all",
        "ledger_path": "project/ledger.md",
        "nested": {"limit": 5},
    }
    assert empty == {}  # input is not mutated


def test_apply_schema_defaults_keeps_present_values_and_expressions():
    schema = {
        "type": "object",
        "properties": {
            "focus": {"type": "string", "default": "all"},
            "nested": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 5}},
            },
        },
    }
    expr = {"$expr": {"kind": "date_math", "version": 1, "anchor": "now"}}
    result = apply_schema_defaults(
        {"focus": expr, "nested": {"limit": 9}}, schema
    )
    assert result["focus"] is expr
    assert result["nested"] == {"limit": 9}


def test_apply_schema_defaults_does_not_inject_into_reference_leaves():
    schema = {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 5}},
            }
        },
    }
    ref = {"$ref": "run.inputs.other"}
    result = apply_schema_defaults({"payload": ref}, schema)
    assert result["payload"] == ref
    assert set(result["payload"]) == {"$ref"}

    piped = {"$ref": "run.inputs.other", "pipe": [{"op": "upper"}]}
    piped_result = apply_schema_defaults({"payload": piped}, schema)
    assert piped_result["payload"] == piped

    expr_root = {"$expr": {"kind": "date_math", "version": 1, "anchor": "now"}}
    assert apply_schema_defaults(expr_root, schema) is expr_root


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


def test_capability_fail_on_output_mismatch_must_be_boolean():
    terminal = _node("t", "terminal", {"outcome": "success"})
    edges = [_edge("e1", "a", "t")]

    invalid = _node(
        "a",
        "capability",
        {
            "capability_key": "vault_read_file",
            "inputs": {"relative_path": "a.md"},
            "fail_on_output_mismatch": "yes",
        },
    )
    errors = validate_graph(nodes=[invalid, terminal], edges=edges)
    assert any("fail_on_output_mismatch" in e for e in errors)

    valid = _node(
        "a",
        "capability",
        {
            "capability_key": "vault_read_file",
            "inputs": {"relative_path": "a.md"},
            "fail_on_output_mismatch": True,
        },
    )
    assert validate_graph(nodes=[valid, terminal], edges=edges) == []


def test_collect_graph_warnings_flags_write_capabilities():
    from obsidian_ai_hub.workflow.validation import collect_graph_warnings

    nodes = [
        _node("a", "capability", {"capability_key": "vault_read_file", "inputs": {}}),
        _node(
            "b",
            "capability",
            {"capability_key": "vault_write_file", "inputs": {}},
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    read_only = {"vault_read_file": True, "vault_write_file": False}
    warnings = collect_graph_warnings(
        nodes=nodes, read_only=lambda key: read_only.get(key, False)
    )
    assert len(warnings) == 1
    assert "vault_write_file" in warnings[0]
    assert collect_graph_warnings(nodes=nodes) == []


def test_collect_graph_warnings_tolerates_non_object_config():
    from obsidian_ai_hub.workflow.validation import collect_graph_warnings

    nodes = [_node("a", "capability", "not-a-dict")]
    assert collect_graph_warnings(
        nodes=nodes, read_only=lambda key: False
    ) == []


def test_collect_graph_warnings_flags_strict_with_retry():
    from obsidian_ai_hub.workflow.validation import collect_graph_warnings

    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_read_file",
                "inputs": {},
                "fail_on_output_mismatch": True,
                "retry": {"max_attempts": 2},
            },
        )
    ]
    warnings = collect_graph_warnings(nodes=nodes, read_only=lambda key: True)
    assert len(warnings) == 1
    assert "strict" in warnings[0]


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
