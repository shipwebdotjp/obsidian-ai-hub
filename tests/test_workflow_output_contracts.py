"""P1/P2 output-contract boundary tests.

Covers the Workflow Capability output-contract ledger (structured / receipt /
opaque), static reference validation at every usage point, P2 strict-ready
read capabilities with fake adapters, strict failure blocking downstream
side effects, and audit detection of legacy whole-output references.
"""

from __future__ import annotations

import json
import uuid

from obsidian_ai_hub.tasks import execution as task_execution
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.runners import DefaultNodeRunner
from obsidian_ai_hub.workflow.validation import validate_graph


def _node(node_id, node_type, config, parent=None):
    node = {
        "node_id": node_id,
        "node_type": node_type,
        "config": config,
    }
    if parent is not None:
        node["parent_loop_node_id"] = parent
    return node


def _edge(edge_id, source, target, *, condition=None, order=0, kind="normal"):
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_kind": kind,
        "condition": condition,
        "order_index": order,
    }


def _strict_reader(node_id="cap_read", key="vault_read_file"):
    return _node(
        node_id,
        "capability",
        {"capability_key": key, "inputs": {}, "fail_on_output_mismatch": True},
    )


def _consumer(ref, node_id="consumer"):
    return _node(
        node_id,
        "agent",
        {
            "agent_id": "agent_x",
            "inputs": {"context": {"$ref": ref}},
            "output_schema": {"type": "object", "properties": {}},
        },
    )


def _terminal(node_id="done"):
    return _node(node_id, "terminal", {"outcome": "success"})


def _validate(nodes, edges, **kwargs):
    return validate_graph(
        nodes=nodes,
        edges=edges,
        inputs_schema={"type": "object", "properties": {}},
        capability_enabled=lambda key: True,
        agent_exists=lambda agent_id: True,
        **kwargs,
    )


# --- static validation: eligible references pass ----------------------------


def test_eligible_strict_structured_field_reference_passes():
    nodes = [
        _strict_reader(),
        _consumer("nodes.cap_read.output.content"),
        _terminal(),
    ]
    edges = [
        _edge("e1", "cap_read", "consumer"),
        _edge("e2", "consumer", "done"),
    ]
    assert _validate(nodes, edges) == []


def test_structured_array_field_reference_passes():
    nodes = [
        _strict_reader(node_id="cal", key="calendar_read"),
        _consumer("nodes.cal.output.events", node_id="c2"),
        _terminal(),
    ]
    edges = [_edge("e1", "cal", "c2"), _edge("e2", "c2", "done")]
    assert _validate(nodes, edges) == []


def test_hitl_wait_answer_reference_passes_with_strict():
    nodes = [
        _node(
            "h",
            "capability",
            {
                "capability_key": "hitl_wait",
                "inputs": {"question": "q"},
                "fail_on_output_mismatch": True,
            },
        ),
        _consumer("nodes.h.output.answer", node_id="c2"),
        _terminal(),
    ]
    edges = [_edge("e1", "h", "c2"), _edge("e2", "c2", "done")]
    assert _validate(nodes, edges) == []


# --- static validation: rejections ------------------------------------------


def test_whole_output_reference_rejected():
    nodes = [
        _strict_reader(),
        _consumer("nodes.cap_read.output"),
        _terminal(),
    ]
    edges = [_edge("e1", "cap_read", "consumer"), _edge("e2", "consumer", "done")]
    errors = _validate(nodes, edges)
    assert any("出力全体" in e for e in errors)


def test_opaque_output_reference_rejected():
    nodes = [
        _node(
            "op",
            "capability",
            {"capability_key": "vault_search", "inputs": {"query": "x"}},
        ),
        _consumer("nodes.op.output.results"),
        _terminal(),
    ]
    edges = [_edge("e1", "op", "consumer"), _edge("e2", "consumer", "done")]
    errors = _validate(nodes, edges)
    assert any("opaque" in e for e in errors)


def test_receipt_output_reference_rejected():
    nodes = [
        _node(
            "w",
            "capability",
            {"capability_key": "vault_write_file", "inputs": {}},
        ),
        _consumer("nodes.w.output.relative_path"),
        _terminal(),
    ]
    edges = [_edge("e1", "w", "consumer"), _edge("e2", "consumer", "done")]
    errors = _validate(nodes, edges)
    assert any("receipt" in e for e in errors)


def test_structured_reference_without_strict_rejected():
    nodes = [
        _node(
            "cap_read",
            "capability",
            {"capability_key": "vault_read_file", "inputs": {}},
        ),
        _consumer("nodes.cap_read.output.content"),
        _terminal(),
    ]
    edges = [
        _edge("e1", "cap_read", "consumer"),
        _edge("e2", "consumer", "done"),
    ]
    errors = _validate(nodes, edges)
    assert any("fail_on_output_mismatch" in e for e in errors)


def test_undeclared_field_reference_rejected():
    nodes = [
        _strict_reader(),
        _consumer("nodes.cap_read.output.no_such_field"),
        _terminal(),
    ]
    edges = [_edge("e1", "cap_read", "consumer"), _edge("e2", "consumer", "done")]
    errors = _validate(nodes, edges)
    assert any("未宣言" in e for e in errors)


def test_array_field_without_index_rejected():
    # ``events.title`` (no index) can never resolve at runtime; only
    # ``events`` or ``events[0].title`` are eligible.
    nodes = [
        _strict_reader(node_id="cal", key="calendar_read"),
        _consumer("nodes.cal.output.events.title", node_id="c2"),
        _terminal(),
    ]
    edges = [_edge("e1", "cal", "c2"), _edge("e2", "c2", "done")]
    errors = _validate(nodes, edges)
    assert any("未宣言" in e for e in errors)


def test_array_indexed_field_reference_passes():
    nodes = [
        _strict_reader(node_id="cal", key="calendar_read"),
        _consumer("nodes.cal.output.events[0].title", node_id="c2"),
        _terminal(),
    ]
    edges = [_edge("e1", "cal", "c2"), _edge("e2", "c2", "done")]
    assert _validate(nodes, edges) == []


def test_undeclared_nesting_reference_rejected():
    nodes = [
        _strict_reader(node_id="snap", key="research_context_snapshot"),
        _consumer("nodes.snap.output.recent_activities.foo"),
        _terminal(),
    ]
    edges = [_edge("e1", "snap", "consumer"), _edge("e2", "consumer", "done")]
    errors = _validate(nodes, edges)
    assert any("未宣言" in e for e in errors)


def test_strict_on_write_capability_rejected():
    nodes = [
        _node(
            "w",
            "capability",
            {
                "capability_key": "vault_write_file",
                "inputs": {},
                "fail_on_output_mismatch": True,
            },
        ),
        _terminal(node_id="done"),
    ]
    edges = [_edge("e1", "w", "done")]
    errors = _validate(nodes, edges)
    assert any("strict_policy" in e for e in errors)


def test_strict_on_receipt_capability_rejected():
    nodes = [
        _node(
            "p",
            "capability",
            {
                "capability_key": "calendar_create_proposal",
                "inputs": {},
                "fail_on_output_mismatch": True,
            },
        ),
        _terminal(node_id="done"),
    ]
    edges = [_edge("e1", "p", "done")]
    errors = _validate(nodes, edges)
    assert any("strict_policy" in e for e in errors)


def test_edge_condition_whole_output_rejected():
    nodes = [_strict_reader(), _terminal(node_id="ok"), _terminal(node_id="ng")]
    edges = [
        _edge(
            "e1",
            "cap_read",
            "ng",
            condition={
                "from_path": "nodes.cap_read.output",
                "operator": "exists",
            },
        ),
        _edge("e2", "cap_read", "ok"),
    ]
    errors = _validate(nodes, edges)
    assert any("出力全体" in e for e in errors)


def test_edge_condition_opaque_rejected():
    nodes = [
        _node(
            "op",
            "capability",
            {"capability_key": "web_search", "inputs": {"query": "x"}},
        ),
        _terminal(node_id="ok"),
        _terminal(node_id="ng"),
    ]
    edges = [
        _edge(
            "e1",
            "op",
            "ng",
            condition={
                "from_path": "nodes.op.output.results",
                "operator": "exists",
            },
        ),
        _edge("e2", "op", "ok"),
    ]
    errors = _validate(nodes, edges)
    assert any("opaque" in e for e in errors)


def test_capability_input_opaque_reference_rejected():
    nodes = [
        _node(
            "op",
            "capability",
            {"capability_key": "vault_search", "inputs": {"query": "x"}},
        ),
        _node(
            "w",
            "capability",
            {
                "capability_key": "vault_write_file",
                "inputs": {
                    "relative_path": "a.md",
                    "content": {"$ref": "nodes.op.output.results"},
                },
            },
        ),
        _terminal(),
    ]
    edges = [_edge("e1", "op", "w"), _edge("e2", "w", "done")]
    errors = _validate(nodes, edges)
    assert any("output_contract" in e for e in errors)


def test_text_template_input_whole_output_rejected():
    nodes = [
        _strict_reader(node_id="snap", key="research_context_snapshot"),
        _node(
            "tt",
            "text_template",
            {
                "inputs": {"ctx": {"$ref": "nodes.snap.output"}},
                "template": "{{ ctx }}",
            },
        ),
        _terminal(),
    ]
    edges = [_edge("e1", "snap", "tt"), _edge("e2", "tt", "done")]
    errors = _validate(nodes, edges)
    assert any("出力全体" in e for e in errors)


def test_loop_input_mapping_opaque_rejected():
    loop_id = "loop1"
    child = _node(
        "child",
        "capability",
        {"capability_key": "vault_read_file", "inputs": {}},
        parent=loop_id,
    )
    result = _node(
        "res",
        "loop_result",
        {"output_mapping": {"draft": "x"}},
        parent=loop_id,
    )
    nodes = [
        _node(
            "op",
            "capability",
            {"capability_key": "vault_search", "inputs": {"query": "x"}},
        ),
        _node(
            loop_id,
            "loop",
            {
                "state_schema": {
                    "type": "object",
                    "properties": {"draft": {"type": "string"}},
                    "required": ["draft"],
                },
                "input_mapping": {"draft": {"$ref": "nodes.op.output.results"}},
                "continuation_condition": {
                    "from_path": "loop.state.draft",
                    "operator": "exists",
                },
                "max_iterations": 2,
                "entry_node_id": "child",
            },
        ),
        child,
        result,
        _terminal(),
    ]
    edges = [
        _edge("e1", "op", loop_id),
        _edge("e2", loop_id, "done"),
        _edge("e3", "child", "res"),
    ]
    errors = _validate(nodes, edges)
    assert any("output_contract" in e for e in errors)


# --- P2 runtime: fake adapters ----------------------------------------------


class _SummaryExecutor:
    def __init__(self, summary: str) -> None:
        self.summary = summary

    def execute_step(self, task, plan, step_index, step):
        return task_execution.StepResult(
            step_index=step_index,
            capability_key=str(step.get("capability_key")),
            summary=self.summary,
        )


def _run_capability(capability_key="vault_read_file", output=None, strict=True):
    """Drive one strict/lenient capability node with a fake JSON output."""
    if output is None:
        output = {"relative_path": "a.md", "content": "body"}
    runner = DefaultNodeRunner()
    runner._executor = _SummaryExecutor(json.dumps(output, ensure_ascii=False))
    node = {
        "node_id": str(uuid.uuid4()),
        "node_type": "capability",
        "config": {
            "capability_key": capability_key,
            **({"fail_on_output_mismatch": True} if strict else {}),
        },
    }
    return runner.run(
        node=node,
        inputs={},
        context={
            "run_id": f"wrun_{uuid.uuid4().hex[:8]}",
            "node_id": node["node_id"],
            "activation_id": str(uuid.uuid4()),
            "attempt": 1,
        },
    )


def _complete_calendar_output():
    return {
        "events": [
            {
                "title": "t",
                "start": "2026-09-21T10:00:00+09:00",
                "end": "2026-09-21T11:00:00+09:00",
                "all_day": False,
                "source": "apple",
            }
        ],
        "apple_status": "ok",
        "recurring_status": "ok",
    }


def test_p2_complete_calendar_output_passes_strict(test_memory_db_path):
    outcome = _run_capability(
        "calendar_read", _complete_calendar_output()
    )
    assert outcome.status == "succeeded"


def test_p2_calendar_partial_result_fails_strict(test_memory_db_path):
    partial = dict(_complete_calendar_output())
    partial["apple_status"] = "unavailable"
    outcome = _run_capability("calendar_read", partial)
    assert outcome.status == "failed"


def test_p2_calendar_missing_required_field_fails_strict(test_memory_db_path):
    bad = {"events": [], "apple_status": "ok"}
    outcome = _run_capability("calendar_read", bad)
    assert outcome.status == "failed"


def test_p2_calendar_null_field_fails_strict(test_memory_db_path):
    bad = dict(_complete_calendar_output())
    bad["events"] = [
        {
            "title": None,
            "start": "2026-09-21T10:00:00+09:00",
            "end": "2026-09-21T11:00:00+09:00",
            "all_day": False,
            "source": "apple",
        }
    ]
    outcome = _run_capability("calendar_read", bad)
    assert outcome.status == "failed"


def test_p2_calendar_unnormalized_event_fails_strict(test_memory_db_path):
    # Legacy Apple shape without ``source`` is a contract violation.
    bad = {
        "events": [
            {
                "title": "t",
                "start": "2026-09-21T10:00:00+09:00",
                "end": "2026-09-21T11:00:00+09:00",
                "all_day": False,
            }
        ],
        "apple_status": "ok",
        "recurring_status": "ok",
    }
    outcome = _run_capability("calendar_read", bad)
    assert outcome.status == "failed"


def test_p2_reminders_complete_output_passes_strict(test_memory_db_path):
    good = {
        "reminders": [{"title": "t", "due": "2026-09-21", "source": "apple"}],
        "apple_status": "ok",
        "recurring_status": "ok",
    }
    outcome = _run_capability("reminders_read", good)
    assert outcome.status == "succeeded"


def test_p2_reminders_partial_result_fails_strict(test_memory_db_path):
    bad = {
        "reminders": [{"title": "t", "due": "2026-09-21", "source": "apple"}],
        "apple_status": "ok",
        "recurring_status": "error",
    }
    outcome = _run_capability("reminders_read", bad)
    assert outcome.status == "failed"


def test_p2_vault_missing_content_fails_strict(test_memory_db_path):
    outcome = _run_capability(
        "vault_read_file", {"relative_path": "a.md"}
    )
    assert outcome.status == "failed"


def test_p2_snapshot_missing_top_level_fails_strict(test_memory_db_path):
    bad = {
        "recent_activities": [],
        "existing_themes": [],
        "recent_feedback": [],
        "daily_notes": [],
    }
    outcome = _run_capability(
        "research_context_snapshot", bad
    )
    assert outcome.status == "failed"


def test_p2_partial_result_stays_observable_without_strict(
    test_memory_db_path,
):
    partial = dict(_complete_calendar_output())
    partial["apple_status"] = "error"
    outcome = _run_capability(
        "calendar_read", partial, strict=False
    )
    assert outcome.status == "succeeded"
    assert outcome.output["apple_status"] == "error"


# --- strict failure blocks downstream side effects ---------------------------


class _CountingExecutor:
    """Fake executor counting external-write invocations."""

    def __init__(self, summaries: dict[str, str]) -> None:
        self.summaries = summaries
        self.writes = 0

    def execute_step(self, task, plan, step_index, step):
        key = str(step.get("capability_key"))
        if key == "vault_write_file":
            self.writes += 1
        return task_execution.StepResult(
            step_index=step_index,
            capability_key=key,
            summary=self.summaries[key],
        )


def test_strict_failure_blocks_downstream_write(test_memory_db_path):
    from obsidian_ai_hub.workflow.execution import WorkflowEngine

    read_id = "nread"
    write_id = "nwrite"
    nodes = [
        {
            "node_id": read_id,
            "node_type": "capability",
            "config": {
                "capability_key": "vault_read_file",
                "inputs": {"relative_path": "missing.md"},
                "fail_on_output_mismatch": True,
            },
        },
        {
            "node_id": write_id,
            "node_type": "capability",
            "config": {
                "capability_key": "vault_write_file",
                "inputs": {
                    "relative_path": "out.md",
                    "content": {"$ref": f"nodes.{read_id}.output.content"},
                },
            },
        },
        {"node_id": "nend", "node_type": "terminal", "config": {"outcome": "success"}},
        {"node_id": "nfail", "node_type": "terminal", "config": {"outcome": "failure"}},
    ]
    edges = [
        {
            "edge_id": "e1",
            "source_node_id": read_id,
            "target_node_id": write_id,
            "edge_kind": "normal",
            "condition": None,
            "order_index": 0,
        },
        {
            "edge_id": "e2",
            "source_node_id": write_id,
            "target_node_id": "nend",
            "edge_kind": "normal",
            "condition": None,
            "order_index": 0,
        },
        {
            "edge_id": "e3",
            "source_node_id": read_id,
            "target_node_id": "nfail",
            "edge_kind": "error",
            "condition": None,
            "order_index": 0,
        },
    ]
    workflow = workflow_store.create_workflow("test-block")
    revision = workflow["revision"]
    workflow_store.set_revision_graph(revision["revision_id"], nodes, edges)
    workflow_store.publish_revision(revision["revision_id"])
    workflow_store.create_run(workflow["workflow_id"], revision["revision_id"], {})
    run = workflow_store.claim_run("test-instance")
    assert run is not None
    # Contract-invalid but resolvable: ``content`` exists so only the
    # strict gate (not input resolution) can stop the downstream write.
    # Without strict the write node would run and ``writes`` would be 1.
    executor = _CountingExecutor(
        {
            "vault_read_file": json.dumps(
                {"relative_path": 123, "content": "hello"}
            ),
            "vault_write_file": json.dumps(
                {
                    "relative_path": "out.md",
                    "bytes_written": 3,
                    "overwritten": False,
                }
            ),
        }
    )
    runner = DefaultNodeRunner()
    runner._executor = executor
    outcome = WorkflowEngine(runner).execute(run)
    assert outcome.kind == "failed"
    assert executor.writes == 0


# --- hitl_wait answer normalization ------------------------------------------


def test_normalize_hitl_answer_coerces_to_string():
    from obsidian_ai_hub.workflow.capabilities import normalize_hitl_answer

    assert normalize_hitl_answer(None) == ""
    assert normalize_hitl_answer("yes") == "yes"
    assert normalize_hitl_answer(True) == "true"
    assert normalize_hitl_answer(False) == "false"
    assert normalize_hitl_answer(5) == "5"
    assert normalize_hitl_answer({"a": 1}) == '{"a":1}'

    from obsidian_ai_hub.workflow.models import validate_value_against_schema
    from obsidian_ai_hub.workflow.capabilities import WORKFLOW_ONLY_OUTPUT_SCHEMA

    schema = WORKFLOW_ONLY_OUTPUT_SCHEMA["hitl_wait"]
    assert "answer" in schema["required"]
    for raw in (None, True, 5, "yes", {"a": 1}):
        normalized = {"answer": normalize_hitl_answer(raw)}
        assert (
            validate_value_against_schema(normalized, schema, path="output")
            == []
        )


# --- starter template stays within the contract ------------------------------


def test_contextual_research_template_passes_contract_validation():
    from obsidian_ai_hub.workflow.templates import build_graph, get_template

    template = get_template("contextual_research")
    assert template is not None
    nodes, edges = build_graph(template)
    for node in nodes:
        if node.get("node_type") == "agent":
            node["config"]["agent_id"] = "agent_x"
    errors = validate_graph(
        nodes=nodes,
        edges=edges,
        inputs_schema=template["inputs_schema"],
        capability_enabled=lambda key: True,
        agent_exists=lambda agent_id: True,
    )
    assert not [e for e in errors if "output_contract" in e]
    assert not [e for e in errors if "strict_policy" in e]


# --- audit: legacy whole-output references are detected ---------------------


def test_audit_detects_legacy_whole_output_references():
    legacy_nodes = [
        _node(
            "snap",
            "capability",
            {"capability_key": "research_context_snapshot", "inputs": {}},
        ),
        _node(
            "ag",
            "agent",
            {
                "agent_id": "agent_x",
                "inputs": {"context": {"$ref": "nodes.snap.output"}},
                "output_schema": {"type": "object", "properties": {}},
            },
        ),
        _terminal(),
    ]
    legacy_edges = [_edge("e1", "snap", "ag"), _edge("e2", "ag", "done")]
    errors = _validate(legacy_nodes, legacy_edges)
    assert any("出力全体" in e for e in errors)

    fixed_nodes = [
        _node(
            "snap",
            "capability",
            {
                "capability_key": "research_context_snapshot",
                "inputs": {},
                "fail_on_output_mismatch": True,
            },
        ),
        _node(
            "ag",
            "agent",
            {
                "agent_id": "agent_x",
                "inputs": {
                    "activities": {
                        "$ref": "nodes.snap.output.recent_activities"
                    }
                },
                "output_schema": {"type": "object", "properties": {}},
            },
        ),
        _terminal(),
    ]
    assert _validate(fixed_nodes, legacy_edges) == []
