"""Capability Node strict output handling.

``fail_on_output_mismatch`` makes a top-level ``error`` output or a declared
output-schema violation fail the Node instead of flowing downstream. The
error-output case matters because registry-tool wrappers report absence (for
example ``vault_read_file`` returns ``{"error": "File not found"}`` with a
successful tool status) and declared schemas allow additional properties.
"""

from __future__ import annotations

import uuid

from obsidian_ai_hub.tasks import execution as task_execution
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.runners import DefaultNodeRunner


class _SummaryExecutor:
    def __init__(self, summary: str) -> None:
        self.summary = summary

    def execute_step(self, task, plan, step_index, step):
        return task_execution.StepResult(
            step_index=step_index,
            capability_key=str(step.get("capability_key")),
            summary=self.summary,
        )


def _runner(summary: str) -> DefaultNodeRunner:
    runner = DefaultNodeRunner()
    runner._executor = _SummaryExecutor(summary)
    return runner


def _run(
    runner: DefaultNodeRunner,
    *,
    run_id: str,
    config: dict | None = None,
    capability_key: str = "vault_read_file",
):
    node = {
        "node_id": str(uuid.uuid4()),
        "node_type": "capability",
        "config": {"capability_key": capability_key, **(config or {})},
    }
    return runner.run(
        node=node,
        inputs={},
        context={
            "run_id": run_id,
            "node_id": node["node_id"],
            "activation_id": str(uuid.uuid4()),
            "attempt": 1,
        },
    )


def _mismatch_events(run_id: str) -> list[dict]:
    return [
        event
        for event in workflow_store.list_events(run_id)
        if event["event_type"] == "capability_output_schema_mismatch"
    ]


def test_strict_error_output_fails_node(test_memory_db_path):
    outcome = _run(
        _runner('{"error": "File not found"}'),
        run_id="wrun_strict_error",
        config={"fail_on_output_mismatch": True},
    )
    assert outcome.status == "failed"
    assert "File not found" in (outcome.error or "")
    assert len(_mismatch_events("wrun_strict_error")) == 1


def test_error_output_passes_without_strict(test_memory_db_path):
    outcome = _run(
        _runner('{"error": "File not found"}'),
        run_id="wrun_lenient_error",
    )
    assert outcome.status == "succeeded"
    assert outcome.output == {"error": "File not found"}
    assert len(_mismatch_events("wrun_lenient_error")) == 1


def test_strict_schema_mismatch_fails_node(test_memory_db_path):
    outcome = _run(
        _runner('{"relative_path": 42, "content": "x"}'),
        run_id="wrun_strict_schema",
        config={"fail_on_output_mismatch": True},
    )
    assert outcome.status == "failed"
    assert "strict" in (outcome.error or "")
    assert len(_mismatch_events("wrun_strict_schema")) == 1


def test_schema_mismatch_passes_without_strict(test_memory_db_path):
    outcome = _run(
        _runner('{"relative_path": 42, "content": "x"}'),
        run_id="wrun_lenient_schema",
    )
    assert outcome.status == "succeeded"
    assert outcome.output == {"relative_path": 42, "content": "x"}
    assert len(_mismatch_events("wrun_lenient_schema")) == 1


def test_matching_output_records_no_event(test_memory_db_path):
    outcome = _run(
        _runner('{"relative_path": "a.md", "content": "body"}'),
        run_id="wrun_match",
        config={"fail_on_output_mismatch": True},
    )
    assert outcome.status == "succeeded"
    assert _mismatch_events("wrun_match") == []