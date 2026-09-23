"""Date-math ``$expr`` language, schema ``format`` and reference-time tests."""

from __future__ import annotations

import pytest

from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.execution import NodeOutcome, WorkflowEngine
from obsidian_ai_hub.workflow.models import (
    evaluate_expression,
    normalize_reference_time,
    parse_date_math,
    validate_expression,
    validate_schema_subset,
    validate_value_against_schema,
)
from obsidian_ai_hub.workflow.validation import validate_graph

REF = "2026-09-23T01:00:00+00:00"  # 2026-09-23 10:00 JST (Wednesday)


def _expr(math="", *, anchor="now", result="date", timezone="Asia/Tokyo",
          week_starts_on="monday"):
    inner = {
        "kind": "date_math",
        "version": 1,
        "anchor": anchor,
        "math": math,
        "timezone": timezone,
        "result": result,
    }
    if week_starts_on is not None:
        inner["week_starts_on"] = week_starts_on
    return {"$expr": inner}


def _eval(value, reference_time=REF):
    return evaluate_expression(
        value, reference_time=reference_time, run_inputs={}, node_outputs={}
    )


# --- language ---------------------------------------------------------------


def test_parse_date_math_grammar():
    assert parse_date_math("/w+6d") == [("/", None, "w"), ("+", 6, "d")]
    assert parse_date_math("-1M") == [("-", 1, "M")]
    assert parse_date_math("") == []
    with pytest.raises(ValueError):
        parse_date_math("+d")
    with pytest.raises(ValueError):
        parse_date_math("/w+6")
    with pytest.raises(ValueError):
        parse_date_math("2d")


def test_known_expressions_with_fixed_reference_time():
    assert _eval(_expr("-1d")) == "2026-09-22"
    assert _eval(_expr("/w")) == "2026-09-21"
    assert _eval(_expr("/w+6d")) == "2026-09-27"
    assert _eval(_expr("-1M/M")) == "2026-08-01"
    assert _eval(_expr("/M+1M-1d")) == "2026-09-30"


def test_month_end_clamp_and_leap_year():
    # 2026-01-31 + 1M -> 2026-02-28 (2026 is not a leap year)
    assert (
        _eval(_expr("+1M"), reference_time="2026-01-31T00:00:00+09:00")
        == "2026-02-28"
    )
    # 2024-01-31 + 1M -> 2024-02-29 (leap year)
    assert (
        _eval(_expr("+1M"), reference_time="2024-01-31T00:00:00+09:00")
        == "2024-02-29"
    )


def test_year_boundary_and_timezone_boundary():
    assert (
        _eval(_expr("+1d"), reference_time="2026-12-31T23:30:00+09:00")
        == "2027-01-01"
    )
    # 2026-09-23T00:30+09:00 is 2026-09-22T15:30Z: UTC date differs from JST.
    utc = _expr("/d", timezone="UTC")
    assert _eval(utc, reference_time="2026-09-23T00:30:00+09:00") == "2026-09-22"
    jst = _expr("/d", timezone="Asia/Tokyo")
    assert _eval(jst, reference_time="2026-09-23T00:30:00+09:00") == "2026-09-23"


def test_week_starts_on_affects_floor():
    # 2026-09-23 is Wednesday.
    assert _eval(_expr("/w", week_starts_on="monday")) == "2026-09-21"
    assert _eval(_expr("/w", week_starts_on="sunday")) == "2026-09-20"


def test_floor_to_hour_minute_second():
    value = _expr("/h", result="datetime")
    assert _eval(value).startswith("2026-09-23T10:00:00+09:00")
    value = _expr("/m", result="datetime")
    assert _eval(value).startswith("2026-09-23T10:00:00+09:00")


def test_datetime_result_has_offset():
    out = _eval(_expr("", result="datetime"))
    assert out == "2026-09-23T10:00:00+09:00"


def test_expression_validation_errors():
    assert validate_expression(_expr("/w+6d")) == []
    assert validate_expression(_expr("+d")) != []
    assert validate_expression(_expr("+1d", timezone="Not/AZone")) != []
    assert validate_expression(_expr("+1d", week_starts_on="funday")) != []
    bad = _expr()
    bad["$expr"]["kind"] = "other"
    assert validate_expression(bad) != []
    bad_version = _expr()
    bad_version["$expr"]["version"] = 2
    assert validate_expression(bad_version) != []
    bad_anchor = _expr()
    bad_anchor["$expr"]["anchor"] = "yesterday"
    assert validate_expression(bad_anchor) != []


def test_expression_result_must_match_target_format():
    date_value = _expr(result="date")
    assert validate_expression(date_value, expected_type="string", expected_format="date") == []
    assert validate_expression(
        date_value, expected_type="string", expected_format="date-time"
    ) != []
    assert validate_expression(date_value, expected_type="integer") != []


# --- schema format ----------------------------------------------------------


def test_schema_subset_accepts_date_formats():
    assert validate_schema_subset({"type": "string", "format": "date"}) == []
    assert validate_schema_subset({"type": "string", "format": "date-time"}) == []
    assert validate_schema_subset({"type": "string", "format": "email"}) != []
    assert validate_schema_subset({"type": "integer", "format": "date"}) != []


def test_format_value_validation():
    schema = {"type": "string", "format": "date"}
    assert validate_value_against_schema("2026-09-23", schema) == []
    assert validate_value_against_schema("2026-13-40", schema) != []
    assert validate_value_against_schema("2026/09/23", schema) != []
    dt_schema = {"type": "string", "format": "date-time"}
    assert validate_value_against_schema("2026-09-23T10:00:00+09:00", dt_schema) == []
    assert validate_value_against_schema("2026-09-23T10:00:00", dt_schema) != []


def test_run_inputs_allow_expression_and_result_type_checked():
    schema = {
        "type": "object",
        "properties": {"day": {"type": "string", "format": "date"}},
        "required": ["day"],
    }
    ok = {"day": _expr("/w+6d")}
    assert validate_value_against_schema(ok, schema, allow_expressions=True) == []
    wrong = {"day": _expr("", result="datetime")}
    assert validate_value_against_schema(wrong, schema, allow_expressions=True) != []
    # Expressions are rejected where they are not allowed (e.g. Agent output).
    assert validate_value_against_schema(ok, schema) != []
    # Run-input anchors may only reference the context, not Nodes.
    node_anchor = _expr(anchor={"$ref": "nodes.n.output.x"})
    assert (
        validate_value_against_schema(
            {"day": node_anchor}, schema, allow_expressions=True
        )
        != []
    )


# --- static graph validation ------------------------------------------------


def _node(node_id, node_type, config, parent=None):
    return {
        "node_id": node_id,
        "node_type": node_type,
        "config": config,
        "parent_loop_node_id": parent,
    }


def _edge(edge_id, source, target):
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_kind": "normal",
        "condition": None,
        "order_index": 0,
    }


def test_validate_graph_rejects_bad_expression():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {"day": _expr("/w+6d")},
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t")]
    assert (
        validate_graph(
            nodes=nodes, edges=edges, inputs_schema={"type": "object"}
        )
        == []
    )

    nodes[0]["config"]["inputs"]["day"] = _expr("+d")
    assert validate_graph(
        nodes=nodes, edges=edges, inputs_schema={"type": "object"}
    ) != []


def test_validate_graph_rejects_non_date_anchor():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {
                    "day": _expr(anchor={"$ref": "run.inputs.count"}),
                },
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t")]
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
    }
    assert (
        validate_graph(nodes=nodes, edges=edges, inputs_schema=schema) != []
    )


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


def test_execution_resolves_node_input_expression():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {"day": _expr("/w+6d")},
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    run = _setup(nodes, [_edge("e1", "a", "t")], reference_time=REF)
    runner = FakeRunner()
    outcome = WorkflowEngine(runner).execute(run)
    assert outcome.kind == "completed"
    assert runner.calls[0][1]["day"] == "2026-09-27"


def test_execution_resolves_run_input_expression():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {"day": {"$ref": "run.inputs.day"}},
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t")]
    run = _setup(
        nodes,
        edges,
        inputs={"day": _expr("/w+6d")},
        inputs_schema={
            "type": "object",
            "properties": {"day": {"type": "string", "format": "date"}},
        },
        reference_time=REF,
    )
    runner = FakeRunner()
    outcome = WorkflowEngine(runner).execute(run)
    assert outcome.kind == "completed"
    assert runner.calls[0][1]["day"] == "2026-09-27"


def test_execution_resolves_context_reference_time():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {"when": {"$ref": "run.context.reference_time"}},
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    run = _setup(nodes, [_edge("e1", "a", "t")], reference_time=REF)
    runner = FakeRunner()
    outcome = WorkflowEngine(runner).execute(run)
    assert outcome.kind == "completed"
    assert runner.calls[0][1]["when"] == normalize_reference_time(REF)


def test_unresolvable_anchor_does_not_call_runner():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {
                    "day": _expr(anchor={"$ref": "nodes.missing.output.day"})
                },
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    run = _setup(nodes, [_edge("e1", "a", "t")], reference_time=REF)
    runner = FakeRunner()
    with pytest.raises((KeyError, ValueError)):
        WorkflowEngine(runner).execute(run)
    assert runner.calls == []


def test_reference_time_persisted_and_rerun_gets_new_time():
    workflow = workflow_store.create_workflow("test", inputs_schema={"type": "object"})
    revision = workflow["revision"]
    workflow_store.set_revision_graph(
        revision["revision_id"],
        [_node("t", "terminal", {"outcome": "success"})],
        [],
    )
    workflow_store.publish_revision(revision["revision_id"])
    run = workflow_store.create_run(
        workflow["workflow_id"],
        revision["revision_id"],
        {},
        reference_time="2026-09-23T01:00:00+00:00",
    )
    assert run["reference_time"] == "2026-09-23T01:00:00+00:00"
    rerun = workflow_store.create_rerun_run(
        workflow_store.get_run(str(run["run_id"])), {}
    )
    assert rerun["reference_time"] != run["reference_time"]
    assert rerun["reference_time"] is not None


def test_validate_graph_accepts_indexed_array_date_anchor():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {"day": _expr(anchor={"$ref": "run.inputs.days[0]"})},
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t")]
    schema = {
        "type": "object",
        "properties": {
            "days": {
                "type": "array",
                "items": {"type": "string", "format": "date"},
            }
        },
    }
    assert validate_graph(nodes=nodes, edges=edges, inputs_schema=schema) == []


def test_validate_graph_rejects_context_suffix():
    nodes = [
        _node(
            "a",
            "capability",
            {
                "capability_key": "vault_search",
                "inputs": {
                    "day": _expr(
                        anchor={"$ref": "run.context.reference_time.extra"}
                    )
                },
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "a", "t")]
    assert (
        validate_graph(
            nodes=nodes, edges=edges, inputs_schema={"type": "object"}
        )
        != []
    )


def test_expression_overflow_is_value_error():
    from obsidian_ai_hub.workflow.models import (
        evaluate_expression,
    )

    huge = {
        "$expr": {
            "kind": "date_math",
            "version": 1,
            "anchor": "now",
            "math": "+3000000d",
            "timezone": "Asia/Tokyo",
            "result": "date",
        }
    }
    with pytest.raises(ValueError):
        evaluate_expression(
            huge, reference_time=REF, run_inputs={}, node_outputs={}
        )
