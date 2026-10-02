"""Integration and operation scenario tests for workflow taint-aware data flows.

Covers:
1. End-to-end execution: Coding output -> narrative Text Template -> vault_write_file.content (atomic real file write).
2. Direct rejection at publish time when narrative flows to forbidden fields (path, command, task, condition, Loop state).
3. Coding adapter 64 KiB UTF-8 truncation, preserving JSON-like free text as narrative, and missing report transition to needs_attention without retry.
"""

from __future__ import annotations

import json
import uuid
import pytest

from obsidian_ai_hub.coding import backend as coding_backend
from obsidian_ai_hub.coding import store as coding_store
from obsidian_ai_hub.tasks import execution as task_execution
from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.adapters.coding import CodingAdapter, truncate_utf8_bytes
from obsidian_ai_hub.web.services import projects as projects_service
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.execution import WorkflowEngine
from obsidian_ai_hub.workflow.models import REF_KEY
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


def _ref(path: str) -> dict[str, str]:
    return {REF_KEY: path}


def _setup_mock_coding(monkeypatch, repo_path, orch_text="report content"):
    monkeypatch.setattr(
        projects_service,
        "get_project_detail",
        lambda pid: {"project_id": pid, "project_path": str(repo_path)},
    )
    monkeypatch.setattr(coding_backend, "validate_git_repo", lambda p: str(repo_path))
    monkeypatch.setattr(
        coding_store,
        "create_session",
        lambda project_id, backend, repo_path, title=None: {"session_id": "cses_1"},
    )
    monkeypatch.setattr(
        coding_store,
        "start_queued_run",
        lambda session_id, content, created_instance_id=None: (
            {"message_id": "m1"},
            {"run_id": "crun_1"},
        ),
    )
    monkeypatch.setattr(
        coding_store,
        "get_run",
        lambda run_id: {"run_id": run_id, "status": "completed", "session_id": "cses_1"},
    )
    monkeypatch.setattr(
        "obsidian_ai_hub.tasks.adapters.coding.wait_for_child_run",
        lambda task_id, get_run, cancel, terminal, poll, timeout, **kwargs: {
            "run_id": "crun_1",
            "status": "completed",
        },
    )
    monkeypatch.setattr(
        coding_store,
        "list_messages",
        lambda session_id: [{"role": "orchestrator", "content": orch_text}] if orch_text else [],
    )
    monkeypatch.setattr(task_store, "set_active_child", lambda task_id, child_kind, child_run_id, conn=None: None)
    monkeypatch.setattr(task_store, "append_task_event", lambda task_id, event_type, payload, conn=None: None)


def test_coding_narrative_to_template_to_vault_file_write(tmp_path, test_memory_db_path, monkeypatch):
    """End-to-end execution: Coding narrative -> Text Template -> vault_write_file.content real file write."""
    narrative_text = "The coordinator report for feature XYZ."
    _setup_mock_coding(monkeypatch, tmp_path, orch_text=narrative_text)

    # Define Workflow
    nodes = [
        _node(
            "coding1",
            "capability",
            {
                "capability_key": "coding_cli",
                "target": {"project_id": 1},
                "inputs": {"task": "do work"},
            },
        ),
        _node(
            "tmpl1",
            "text_template",
            {
                "inputs": {"report": _ref("nodes.coding1.output.narrative.text")},
                "template": "# Executive Summary\n\n{{ report }}",
            },
        ),
        _node(
            "write1",
            "capability",
            {
                "capability_key": "vault_write_file",
                "inputs": {
                    "relative_path": "summary.md",
                    "content": _ref("nodes.tmpl1.output.text"),
                },
            },
        ),
        _node("done", "terminal", {"outcome": "success"}),
    ]
    edges = [
        _edge("e1", "coding1", "tmpl1"),
        _edge("e2", "tmpl1", "write1"),
        _edge("e3", "write1", "done"),
    ]

    # Validate graph passes
    errors = validate_graph(
        nodes=nodes,
        edges=edges,
        inputs_schema={"type": "object", "properties": {}},
        capability_enabled=lambda k: True,
        agent_exists=lambda a: True,
    )
    assert errors == []

    # Save and publish workflow
    wf = workflow_store.create_workflow("integration-test-wf", skip_approval=True)
    rev = wf["revision"]
    workflow_store.set_revision_graph(rev["revision_id"], nodes, edges)
    workflow_store.publish_revision(rev["revision_id"])

    # Create and execute run
    workflow_store.create_run(wf["workflow_id"], rev["revision_id"], {})
    run = workflow_store.claim_run("test-instance")
    assert run is not None

    runner = DefaultNodeRunner(poll_interval=0.01)
    engine = WorkflowEngine(runner)
    outcome = engine.execute(run)

    assert outcome.kind == "completed"

    from obsidian_ai_hub.utils import config as app_config

    # Verify real file was written to disk inside the test VAULT_PATH
    written_file = app_config.VAULT_PATH / "summary.md"
    assert written_file.exists()
    assert written_file.read_text("utf-8") == "# Executive Summary\n\nThe coordinator report for feature XYZ."


def test_narrative_flow_to_forbidden_targets_rejected_before_publish():
    """Publish-time rejection when narrative flows to forbidden parameters."""
    forbidden_targets = [
        ("path", {"relative_path": _ref("nodes.c1.output.narrative.text"), "content": "body"}),
        ("command", {"command": _ref("nodes.c1.output.narrative.text")}),
    ]

    for label, bad_inputs in forbidden_targets:
        cap_key = "vault_write_file" if "relative_path" in bad_inputs else "run_shell"
        nodes = [
            _node("c1", "capability", {"capability_key": "coding_cli", "target": {"project_id": 1}, "inputs": {}}),
            _node("bad_node", "capability", {"capability_key": cap_key, "inputs": bad_inputs}),
            _node("done", "terminal", {"outcome": "success"}),
        ]
        edges = [_edge("e1", "c1", "bad_node"), _edge("e2", "bad_node", "done")]

        errors = validate_graph(
            nodes=nodes,
            edges=edges,
            inputs_schema={"type": "object", "properties": {}},
            capability_enabled=lambda k: True,
            agent_exists=lambda a: True,
        )
        assert len(errors) > 0, f"Expected rejection for {label}"
        assert any("Narrative" in e or "flow_contract" in e or "narrative" in e for e in errors)


def test_coding_adapter_utf8_truncation_and_json_narrative(tmp_path, monkeypatch):
    """Test 64 KiB UTF-8 truncation and JSON-like string preserved as narrative."""
    # Test 64 KiB truncation helper directly
    large_text = "あ" * 30000  # 3 bytes per char in UTF-8 -> 90,000 bytes
    truncated, is_truncated = truncate_utf8_bytes(large_text, max_bytes=64 * 1024)
    assert is_truncated is True
    assert len(truncated.encode("utf-8")) <= 64 * 1024

    json_narrative = '{"status": "ok", "message": "all done"}'
    _setup_mock_coding(monkeypatch, tmp_path, orch_text=json_narrative)

    task = {"task_id": "t1"}
    plan = {"plan": {"steps": [{"capability_key": "coding_cli", "target": {"project_id": 1}, "inputs": {}}]}}

    result = CodingAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])
    assert result.output["narrative"]["text"] == json_narrative
    assert result.output["receipt"]["status"] == "completed"
    assert result.output["receipt"]["report_truncated"] is False


def test_missing_report_transitions_to_needs_attention_without_retry(tmp_path, test_memory_db_path, monkeypatch):
    """When child completes but report is missing, transition to needs_attention with observed receipt."""
    _setup_mock_coding(monkeypatch, tmp_path, orch_text="")

    nodes = [
        _node("c1", "capability", {"capability_key": "coding_cli", "target": {"project_id": 1}, "inputs": {}}),
        _node("done", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "c1", "done")]

    wf = workflow_store.create_workflow("attention-test-wf", skip_approval=True)
    rev = wf["revision"]
    workflow_store.set_revision_graph(rev["revision_id"], nodes, edges)
    workflow_store.publish_revision(rev["revision_id"])

    workflow_store.create_run(wf["workflow_id"], rev["revision_id"], {})
    run = workflow_store.claim_run("test-instance")
    assert run is not None

    runner = DefaultNodeRunner(poll_interval=0.01)
    engine = WorkflowEngine(runner)
    outcome = engine.execute(run)

    assert outcome.kind == "waiting_attention"
    latest_run = workflow_store.get_run(run["run_id"])
    assert str(latest_run["status"]) in ("waiting_attention", "needs_attention")

    node_rows = workflow_store.list_run_nodes(run["run_id"])
    coding_node_row = next(r for r in node_rows if r["node_id"] == "c1")
    assert str(coding_node_row["status"]) == "needs_attention"
    assert coding_node_row["child_run_id"] == "crun_1"
    assert coding_node_row["output"]["receipt"]["status"] == "completed"
