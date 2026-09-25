"""Single-shot ``llm`` Workflow node tests with a fake provider.

Covers the non-conversational contract: typed JSON output, independent
``llm_call_logs`` rows (``run_id`` NULL), no Agent conversation rows, no
approval gate, static validation, and cancel/stop behavior.
"""

from __future__ import annotations

from typing import Any

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.workflow import llm_node
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.runners import DefaultNodeRunner
from obsidian_ai_hub.workflow.validation import validate_graph

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata = {
            "input_tokens": 3,
            "output_tokens": 5,
            "total_tokens": 8,
        }
        self.response_metadata = {"finish_reason": "stop"}


class _FakeLLM:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[list[Any]] = []

    def invoke(self, messages: list[Any]) -> Any:
        self.calls.append(messages)
        if isinstance(self.result, Exception):
            raise self.result
        return _FakeMessage(self.result)


def _patch_llm(monkeypatch, fake: _FakeLLM) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def factory(**kwargs: Any) -> _FakeLLM:
        captured.update(kwargs)
        return fake

    monkeypatch.setattr(llm_node, "create_langchain_llm", factory)
    return captured


def _llm_config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "provider": "openai",
        "model": "gpt-test",
        "system_prompt": "You answer.",
        "max_tokens": 4096,
        "inputs": {},
        "output_schema": OUTPUT_SCHEMA,
    }
    config.update(overrides)
    return config


def _node(node_id: str, node_type: str, config: dict[str, Any]) -> dict[str, Any]:
    return {"node_id": node_id, "node_type": node_type, "config": config}


def _edge(edge_id: str, source: str, target: str, kind: str = "normal"):
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_kind": kind,
        "condition": None,
        "order_index": 0,
    }


def _setup(nodes, edges, inputs=None):
    workflow = workflow_store.create_workflow(
        "llm-test", inputs_schema={"type": "object"}
    )
    revision = workflow["revision"]
    workflow_store.set_revision_graph(revision["revision_id"], nodes, edges)
    workflow_store.publish_revision(revision["revision_id"])
    workflow_store.create_run(
        workflow["workflow_id"], revision["revision_id"], inputs or {}
    )
    claimed = workflow_store.claim_run("llm-instance")
    assert claimed is not None
    return claimed


def _count(table: str) -> int:
    allowed = {"agent_sessions", "agent_messages", "agent_runs"}
    if table not in allowed:
        raise ValueError(f"unexpected table: {table}")
    conn = get_db_connection()
    try:
        return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
    finally:
        conn.close()


def _llm_log_rows() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM llm_call_logs ORDER BY started_at"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def test_llm_node_runs_json_and_logs_independently(test_memory_db_path, monkeypatch):
    fake = _FakeLLM('{"answer": "ok"}')
    captured = _patch_llm(monkeypatch, fake)
    run = _setup(
        [
            _node("llm", "llm", _llm_config(inputs={"task": "q"})),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [_edge("e1", "llm", "t")],
    )

    outcome = DefaultNodeRunner().run(
        node=_node("llm", "llm", _llm_config(inputs={"task": "q"})),
        inputs={"task": "q"},
        context={
            "run_id": run["run_id"],
            "node_id": "llm",
            "activation_id": "act-1",
        },
    )
    assert outcome.status == "succeeded"
    assert outcome.output == {"answer": "ok"}
    assert captured["temperature"] == 0.7
    assert captured["store"] is False
    assert len(fake.calls) == 1

    logs = _llm_log_rows()
    assert len(logs) == 1
    log = logs[0]
    assert log["run_id"] is None
    assert log["provider"] == "openai"
    assert log["model"] == "gpt-test"
    assert log["status"] == "succeeded"
    assert log["response"] == '{"answer": "ok"}'
    assert log["total_tokens"] == 8

    # The LLM Node must not create an Agent conversation.
    assert _count("agent_sessions") == 0
    assert _count("agent_messages") == 0
    assert _count("agent_runs") == 0


def test_llm_engine_success_end_to_end(test_memory_db_path, monkeypatch):
    fake = _FakeLLM('{"answer": "ok"}')
    _patch_llm(monkeypatch, fake)
    run = _setup(
        [
            _node("llm", "llm", _llm_config()),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [_edge("e1", "llm", "t")],
    )
    from obsidian_ai_hub.workflow.execution import WorkflowEngine

    outcome = WorkflowEngine(DefaultNodeRunner()).execute(run)
    assert outcome.kind == "completed"
    nodes = {
        node["node_id"]: node for node in workflow_store.list_run_nodes(run["run_id"])
    }
    assert nodes["llm"]["status"] == "succeeded"


def test_opencode_go_uses_activation_session(test_memory_db_path, monkeypatch):
    fake = _FakeLLM('{"answer": "ok"}')
    captured = _patch_llm(monkeypatch, fake)
    run = _setup(
        [
            _node("llm", "llm", _llm_config(provider="opencode_go", model="kimi-x")),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [_edge("e1", "llm", "t")],
    )
    from obsidian_ai_hub.workflow.execution import WorkflowEngine

    outcome = WorkflowEngine(DefaultNodeRunner()).execute(run)
    assert outcome.kind == "completed"
    assert captured["session_id"]
    assert "store" not in captured
    activation = workflow_store.find_activation(run["run_id"], "llm", None)
    assert activation is not None
    assert captured["session_id"] == activation["activation_id"]


def test_invalid_json_fails_node(test_memory_db_path, monkeypatch):
    _patch_llm(monkeypatch, _FakeLLM("not json at all"))
    run = _setup(
        [
            _node("llm", "llm", _llm_config()),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [_edge("e1", "llm", "t")],
    )
    from obsidian_ai_hub.workflow.execution import WorkflowEngine

    outcome = WorkflowEngine(DefaultNodeRunner()).execute(run)
    assert outcome.kind == "failed"


def test_schema_mismatch_fails_node(test_memory_db_path, monkeypatch):
    _patch_llm(monkeypatch, _FakeLLM('{"answer": 1}'))
    run = _setup(
        [
            _node("llm", "llm", _llm_config()),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [_edge("e1", "llm", "t")],
    )
    from obsidian_ai_hub.workflow.execution import WorkflowEngine

    outcome = WorkflowEngine(DefaultNodeRunner()).execute(run)
    assert outcome.kind == "failed"


def test_provider_error_logs_failure_and_fails_node(test_memory_db_path, monkeypatch):
    _patch_llm(monkeypatch, _FakeLLM(RuntimeError("provider boom")))
    run = _setup(
        [
            _node("llm", "llm", _llm_config()),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [_edge("e1", "llm", "t")],
    )
    from obsidian_ai_hub.workflow.execution import WorkflowEngine

    outcome = WorkflowEngine(DefaultNodeRunner()).execute(run)
    assert outcome.kind == "failed"
    logs = _llm_log_rows()
    assert len(logs) == 1
    assert logs[0]["status"] == "failed"
    assert "provider boom" in (logs[0]["exception_message"] or "")


def test_error_edge_routes_llm_failure(test_memory_db_path, monkeypatch):
    _patch_llm(monkeypatch, _FakeLLM("not json"))
    run = _setup(
        [
            _node("llm", "llm", _llm_config()),
            _node("tf", "terminal", {"outcome": "failure"}),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [
            _edge("e1", "llm", "tf", kind="error"),
            _edge("e2", "llm", "t"),
        ],
    )
    from obsidian_ai_hub.workflow.execution import WorkflowEngine

    outcome = WorkflowEngine(DefaultNodeRunner()).execute(run)
    assert outcome.kind == "failed"


def test_llm_cancel_before_send_does_not_call_provider(
    test_memory_db_path, monkeypatch
):
    fake = _FakeLLM('{"answer": "ok"}')
    _patch_llm(monkeypatch, fake)
    run = _setup(
        [_node("llm", "llm", _llm_config())],
        [],
    )
    activation_id = workflow_store.get_or_create_activation(
        run["run_id"], "llm", None
    )
    workflow_store.request_run_cancel(run["run_id"])
    outcome = DefaultNodeRunner().run(
        node={"node_id": "llm", "node_type": "llm", "config": _llm_config()},
        inputs={},
        context={
            "run_id": run["run_id"],
            "node_id": "llm",
            "activation_id": activation_id,
        },
    )
    assert outcome.status == "cancelled"
    assert fake.calls == []
    assert _llm_log_rows() == []


def test_llm_cancel_during_send_stops_before_next_node(
    test_memory_db_path, monkeypatch
):
    run = _setup(
        [
            _node("llm", "llm", _llm_config()),
            _node("t", "terminal", {"outcome": "success"}),
        ],
        [_edge("e1", "llm", "t")],
    )

    class _CancellingLLM(_FakeLLM):
        def invoke(self, messages):
            workflow_store.request_run_cancel(run["run_id"])
            return super().invoke(messages)

    _patch_llm(monkeypatch, _CancellingLLM('{"answer": "ok"}'))
    from obsidian_ai_hub.workflow.execution import WorkflowEngine

    outcome = WorkflowEngine(DefaultNodeRunner()).execute(run)
    assert outcome.kind == "cancelled"
    assert workflow_store.get_run(run["run_id"])["status"] == "cancelled"
    executed = {node["node_id"] for node in workflow_store.list_run_nodes(run["run_id"])}
    assert "t" not in executed
    # The in-flight output is preserved for audit.
    llm_node_row = next(
        node
        for node in workflow_store.list_run_nodes(run["run_id"])
        if node["node_id"] == "llm"
    )
    assert llm_node_row["status"] == "succeeded"


def test_llm_node_does_not_require_approval(test_memory_db_path):
    from obsidian_ai_hub.workflow.scheduling import requires_approval

    assert requires_approval([_node("llm", "llm", _llm_config())]) is False


def test_llm_static_validation(test_memory_db_path):
    base_nodes = [
        _node("llm", "llm", _llm_config()),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    assert validate_graph(nodes=base_nodes, edges=[_edge("e1", "llm", "t")]) == []

    bad = _llm_config()
    bad.pop("output_schema")
    bad["retry"] = {"max_attempts": 3}
    errors = validate_graph(
        nodes=[_node("llm", "llm", bad), base_nodes[1]],
        edges=[_edge("e1", "llm", "t")],
    )
    assert any("未知のキー" in error and "retry" in error for error in errors)
    assert any("output_schema" in error for error in errors)

    effort = _llm_config(provider="gemini", reasoning_effort="high")
    errors = validate_graph(
        nodes=[_node("llm", "llm", effort), base_nodes[1]],
        edges=[_edge("e1", "llm", "t")],
    )
    assert any("reasoning_effort" in error for error in errors)

    # An unhashable provider must produce a validation error, not a crash.
    unhashable = _llm_config(provider=["openai"], reasoning_effort="high")
    errors = validate_graph(
        nodes=[_node("llm", "llm", unhashable), base_nodes[1]],
        edges=[_edge("e1", "llm", "t")],
    )
    assert any(".provider" in error for error in errors)


def test_llm_output_reference_type_resolution(test_memory_db_path):
    nodes = [
        _node("llm", "llm", _llm_config()),
        _node(
            "tt",
            "text_template",
            {
                "inputs": {
                    "v": {
                        "$ref": "nodes.llm.output.answer",
                        "pipe": [{"op": "upper"}],
                    }
                },
                "template": "{{ v }}",
            },
        ),
        _node("t", "terminal", {"outcome": "success"}),
    ]
    errors = validate_graph(
        nodes=nodes,
        edges=[_edge("e1", "llm", "tt"), _edge("e2", "tt", "t")],
    )
    assert errors == []
