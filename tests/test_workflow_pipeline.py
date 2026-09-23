"""Value pipeline (``$ref.pipe``) and ``text_template`` node tests."""

from __future__ import annotations

import pytest

from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.execution import NodeOutcome, WorkflowEngine
from obsidian_ai_hub.workflow.models import (
    apply_pipe,
    validate_pipe,
)
from obsidian_ai_hub.workflow.text_template import (
    render_template,
    validate_template,
)
from obsidian_ai_hub.workflow.validation import validate_graph


def _node(node_id, node_type, config, parent=None):
    return {
        "node_id": node_id,
        "node_type": node_type,
        "config": config,
        "parent_loop_node_id": parent,
    }


def _edge(edge_id, source, target, *, kind="normal"):
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_kind": kind,
        "condition": None,
        "order_index": 0,
    }


# --- pipe language ----------------------------------------------------------


def test_validate_pipe_accepts_each_operator():
    assert validate_pipe([{"op": "upper"}, {"op": "lower"}]) == []
    assert validate_pipe([{"op": "truncate", "args": {"max_len": 5}}]) == []
    assert validate_pipe([{"op": "slice", "args": {"limit": 3, "offset": 1}}]) == []
    assert validate_pipe([{"op": "replace", "args": {"frm": "a", "to": "b"}}]) == []
    assert validate_pipe([{"op": "pluck", "args": {"key": "title"}}]) == []
    assert validate_pipe([{"op": "join", "args": {"sep": ","}}]) == []
    assert validate_pipe([{"op": "default", "args": {"value": []}}]) == []


def test_validate_pipe_rejects_bad_ops_and_args():
    assert validate_pipe("nope") != []
    assert validate_pipe([]) != []
    assert validate_pipe([{"op": "unknown"}]) != []
    assert validate_pipe([{"op": "upper", "args": {"x": 1}}]) != []
    assert validate_pipe([{"op": "truncate"}]) != []
    assert validate_pipe([{"op": "truncate", "args": {"max_len": -1}}]) != []
    assert validate_pipe([{"op": "slice", "args": {"limit": 1, "offset": -1}}]) != []
    assert validate_pipe([{"op": "replace", "args": {"frm": ""}}]) != []
    assert validate_pipe([{"op": "pluck", "args": {}}]) != []
    assert validate_pipe([{"op": "join", "args": {"sep": 1}}]) != []
    assert validate_pipe([{"op": "default", "args": {}}]) != []
    too_many = [{"op": "upper"}] * 21
    assert validate_pipe(too_many) != []


def test_validate_pipe_rejects_nested_references():
    pipe = [{"op": "default", "args": {"value": {"$ref": "run.inputs.x"}}}]
    assert validate_pipe(pipe) != []


def test_apply_pipe_chain_and_ordering():
    events = [{"title": "Alpha"}, {"title": "Beta"}, {"title": "Gamma"}]
    pipe = [
        {"op": "slice", "args": {"limit": 2}},
        {"op": "pluck", "args": {"key": "title"}},
        {"op": "join", "args": {"sep": ", "}},
        {"op": "upper"},
        {"op": "truncate", "args": {"max_len": 6}},
    ]
    assert apply_pipe(events, pipe) == "ALPHA,"


def test_apply_pipe_type_mismatch_and_missing_key():
    with pytest.raises(ValueError):
        apply_pipe(123, [{"op": "upper"}])
    with pytest.raises(ValueError):
        apply_pipe("x", [{"op": "pluck", "args": {"key": "k"}}])
    with pytest.raises(ValueError):
        apply_pipe([{"other": 1}], [{"op": "pluck", "args": {"key": "k"}}])


def test_apply_pipe_default_and_join_stringify():
    assert apply_pipe(None, [{"op": "default", "args": {"value": "x"}}]) == "x"
    assert apply_pipe("", [{"op": "default", "args": {"value": "x"}}]) == "x"
    assert apply_pipe([], [{"op": "default", "args": {"value": "x"}}]) == "x"
    assert apply_pipe(0, [{"op": "default", "args": {"value": "x"}}]) == 0
    assert apply_pipe(False, [{"op": "default", "args": {"value": "x"}}]) is False
    assert apply_pipe([1, True, None, {"a": 1}], [{"op": "join", "args": {"sep": "|"}}]) == (
        '1|true||{"a":1}'
    )


# --- text_template validation/render ---------------------------------------


def test_validate_template_variables_and_syntax():
    assert validate_template("{{ events }}", allowed_variables=["events"]) == []
    assert validate_template("{{ missing }}", allowed_variables=["events"]) != []
    assert validate_template("{% for x in %}", allowed_variables=["events"]) != []
    assert validate_template(123, allowed_variables=[]) != []
    assert validate_template("{{ range(3) }}", allowed_variables=[]) == []


def test_render_template_features_and_limits():
    template = (
        "{% if events %}予定:\n"
        "{% for e in events %}- {{ e.title | upper }}\n{% endfor %}"
        "{% else %}なし{% endif %}"
    )
    rendered = render_template(template, {"events": [{"title": "a"}], "n": 1})
    assert "- A" in rendered
    assert render_template("{{ x | default('z') }}", {}) == "z"
    with pytest.raises(ValueError):
        render_template("{{ ''.__class__ }}", {})
    with pytest.raises(ValueError):
        render_template("{{ x }}", {"x": "a" * (64 * 1024 + 1)})


# --- graph validation -------------------------------------------------------


def test_validate_graph_pipe_and_text_template():
    pipe = [{"op": "slice", "args": {"limit": 1}}]
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {"q": {"$ref": "run.inputs.q", "pipe": pipe}},
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t")]
    schema = {"type": "object", "properties": {"q": {"type": "array"}}}
    assert validate_graph(nodes=nodes, edges=edges, inputs_schema=schema) == []

    nodes[0]["config"]["inputs"]["q"] = {
        "$ref": "run.inputs.q",
        "pipe": [{"op": "bogus"}],
    }
    assert validate_graph(nodes=nodes, edges=edges, inputs_schema=schema) != []


def test_validate_graph_text_template_unknown_variable():
    nodes = [
        _node(
            "tt",
            "text_template",
            {"inputs": {"events": {"$ref": "run.inputs.events"}}, "template": "{{ other }}"},
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "tt", "t")]
    schema = {"type": "object", "properties": {"events": {"type": "array"}}}
    errors = validate_graph(nodes=nodes, edges=edges, inputs_schema=schema)
    assert any("other" in e for e in errors)


# --- execution --------------------------------------------------------------


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, *, node, inputs, context):
        self.calls.append((node["node_id"], inputs))
        return NodeOutcome(status="succeeded", output={"ok": True})


def _setup(nodes, edges, inputs=None, inputs_schema=None, reference_time=None):
    workflow = workflow_store.create_workflow(
        "test", inputs_schema=inputs_schema or {"type": "object"}
    )
    revision = workflow["revision"]
    workflow_store.set_revision_graph(revision["revision_id"], nodes, edges)
    workflow_store.publish_revision(revision["revision_id"])
    workflow_store.create_run(
        workflow["workflow_id"],
        revision["revision_id"],
        inputs or {},
        reference_time=reference_time,
    )
    claimed = workflow_store.claim_run("test-instance")
    assert claimed is not None
    return claimed


def test_execution_applies_pipe_to_capability_input():
    nodes = [
        _node(
            "src",
            "capability",
            {"capability_key": "calendar_read", "inputs": {}},
        ),
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {
                    "q": {
                        "$ref": "nodes.src.output.events",
                        "pipe": [
                            {"op": "slice", "args": {"limit": 2}},
                            {"op": "pluck", "args": {"key": "title"}},
                            {"op": "join", "args": {"sep": ", "}},
                        ],
                    }
                },
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "src", "a"), _edge("e2", "a", "t")]

    class Runner:
        def __init__(self):
            self.calls = []

        def run(self, *, node, inputs, context):
            self.calls.append((node["node_id"], inputs))
            if node["node_id"] == "src":
                return NodeOutcome(
                    status="succeeded",
                    output={"events": [{"title": "A"}, {"title": "B"}, {"title": "C"}]},
                )
            return NodeOutcome(status="succeeded", output={})

    runner = Runner()
    outcome = WorkflowEngine(runner).execute(_setup(nodes, edges))
    assert outcome.kind == "completed"
    assert runner.calls[1][1]["q"] == "A, B"


def test_execution_pipe_error_routes_to_error_edge():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {
                    "q": {
                        "$ref": "run.inputs.bad",
                        "pipe": [{"op": "pluck", "args": {"key": "k"}}],
                    }
                },
            },
        ),
        _node("recover", "terminal", {"outcome": "success"}),
        _node("wrong", "terminal", {"outcome": "failure"}),
    ]
    edges = [
        _edge("e1", "a", "recover", kind="error"),
        _edge("e2", "a", "wrong"),
    ]
    schema = {"type": "object", "properties": {"bad": {"type": "integer"}}}
    runner = FakeRunner()
    outcome = WorkflowEngine(runner).execute(
        _setup(nodes, edges, inputs={"bad": 1}, inputs_schema=schema)
    )
    assert runner.calls == []
    # Reaching the error-edge target (success terminal) proves the route.
    assert outcome.kind == "completed"


def test_execution_text_template_and_downstream_reference():
    template = "{% for e in events %}- {{ e.title }}\n{% endfor %}"
    nodes = [
        _node(
            "tt",
            "text_template",
            {
                "inputs": {"events": {"$ref": "run.inputs.events"}},
                "template": template,
            },
        ),
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {"q": {"$ref": "nodes.tt.output.text"}},
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "tt", "a"), _edge("e2", "a", "t")]
    schema = {"type": "object", "properties": {"events": {"type": "array"}}}
    runner = FakeRunner()
    outcome = WorkflowEngine(runner).execute(
        _setup(
            nodes,
            edges,
            inputs={"events": [{"title": "A"}, {"title": "B"}]},
            inputs_schema=schema,
        )
    )
    assert outcome.kind == "completed"
    assert runner.calls[0][1]["q"] == "- A\n- B\n"


def test_text_template_node_never_requires_approval():
    from obsidian_ai_hub.workflow.scheduling import requires_approval

    nodes = [
        _node("tt", "text_template", {"inputs": {}, "template": "x"}),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    assert requires_approval(nodes) is False


def test_pipe_survives_graph_copy_remap():
    from obsidian_ai_hub.workflow.graph_copy import renumber_graph

    nodes = [
        _node(
            "00000000-0000-0000-0000-000000000001",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {
                    "q": {
                        "$ref": "nodes.00000000-0000-0000-0000-000000000002.output.x",
                        "pipe": [{"op": "upper"}],
                    }
                },
            },
        ),
        _node("00000000-0000-0000-0000-000000000002", "terminal", {"outcome": "success"}),
    ]
    ids = iter(["n1", "n2"])
    cloned, _ = renumber_graph(nodes, [], id_factory=lambda: next(ids))
    ref = cloned[0]["config"]["inputs"]["q"]
    assert ref["pipe"] == [{"op": "upper"}]
    assert ref["$ref"] == "nodes.n2.output.x"


def test_calendar_read_output_schema_declares_event_fields():
    from obsidian_ai_hub.tasks.capability_schemas import capability_output_schema

    schema = capability_output_schema("calendar_read")
    events = schema["properties"]["events"]["items"]
    assert "title" in events["properties"]
    assert "start" in events["properties"]


def test_apply_pipe_normalizes_explicit_null_optional_args():
    assert apply_pipe([1, 2, 3], [{"op": "slice", "args": {"limit": 2, "offset": None}}]) == [1, 2]
    assert apply_pipe("abc", [{"op": "replace", "args": {"frm": "b", "to": None}}]) == "ac"
    assert apply_pipe(["a", "b"], [{"op": "join", "args": {"sep": None}}]) == "ab"


def test_render_template_wraps_non_template_errors():
    # ``round`` on a string raises TypeError, which must become ValueError so the
    # node-failure path (not a worker crash) handles it.
    with pytest.raises(ValueError):
        render_template("{{ s | round }}", {"s": "abc"})


def test_render_template_rejects_oversized_body():
    with pytest.raises(ValueError):
        render_template("x" * (16 * 1024 + 1), {})


def test_validate_template_rejects_includes():
    assert validate_template('{% include "x" %}', allowed_variables=[]) != []
    assert validate_template('{% extends "base" %}', allowed_variables=[]) != []


def test_validate_graph_rejects_malformed_reference_shape():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {"q": {"$ref": "run.inputs.q", "pipe": "upper"}},
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t")]
    errors = validate_graph(
        nodes=nodes, edges=edges, inputs_schema={"type": "object", "properties": {"q": {}}}
    )
    assert any("$ref" in e for e in errors)


def test_render_template_allows_input_named_self():
    # ``self`` is a reserved Jinja name, but it must not crash the render
    # (``render(**variables)`` used to raise a duplicate-argument TypeError).
    assert render_template("ok", {"self": "x"}) == "ok"
    assert render_template("{{ other }}", {"self": "x", "other": "y"}) == "y"
