"""Tests for gmail_create_draft receipt capability and at-most-once execution contract.

Covers:
1. Input field contracts: narrative allowed for body_text and subject, rejected for to, cc, bcc, mode, reply_to_message_id, reply_all.
2. Output receipt contract: all receipt fields forbidden from downstream references/conditions.
3. End-to-end integration: mixed narrative -> Text Template -> gmail_create_draft -> fake Gmail API.
4. Action request key idempotency: same key + same hash reuses receipt without second API call.
5. Input hash mismatch: halts in needs_attention without calling Gmail API or retrying.
6. Pending/unknown ledger status: halts in needs_attention without retrying.
7. Local receipt persistence failure: captures acquired IDs and halts in needs_attention with receipt_persisted=False.
8. Dispatch/transport error: sets status to unknown and halts in needs_attention.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from obsidian_ai_hub.gmail import store as gmail_store
from obsidian_ai_hub.gmail.client import GmailService
from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.adapters.gmail import GmailDraftAdapter
from obsidian_ai_hub.tasks.capability_schemas import (
    ALLOWED_USES_NONE,
    VALUE_KIND_RECEIPT,
    get_input_field_contract,
    get_output_field_contract,
    output_contract_class,
)
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.execution import WorkflowEngine
from obsidian_ai_hub.workflow.models import REF_KEY
from obsidian_ai_hub.workflow.runners import DefaultNodeRunner
from obsidian_ai_hub.workflow.validation import validate_graph


def _node(node_id: str, node_type: str, config: dict[str, Any]) -> dict[str, Any]:
    return {"node_id": node_id, "node_type": node_type, "config": config}


def _edge(edge_id: str, source: str, target: str, condition: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_kind": "normal",
        "condition": condition,
        "order_index": 0,
    }


def _ref(path: str) -> dict[str, str]:
    return {REF_KEY: path}


def _validate(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    return validate_graph(
        nodes=nodes,
        edges=edges,
        inputs_schema={"type": "object", "properties": {}},
        capability_enabled=lambda k: True,
        agent_exists=lambda a: True,
    )


# --- 1. Contract & Validation Tests ---


def test_gmail_create_draft_capability_class_and_contracts():
    assert output_contract_class("gmail_create_draft") == "receipt"

    for field in (
        "status",
        "request_key",
        "gmail_draft_id",
        "gmail_message_id",
        "gmail_thread_id",
        "reused_receipt",
        "receipt_persisted",
    ):
        contract = get_output_field_contract("gmail_create_draft", field)
        assert contract["value_kind"] == VALUE_KIND_RECEIPT
        assert contract["allowed_uses"] == ALLOWED_USES_NONE

    assert get_input_field_contract("gmail_create_draft", "body_text") == {
        "accepted_value_kinds": ["structured", "narrative"]
    }
    assert get_input_field_contract("gmail_create_draft", "subject") == {
        "accepted_value_kinds": ["structured", "narrative"]
    }

    for structured_only_field in ("mode", "to", "cc", "bcc", "reply_to_message_id", "reply_all"):
        assert get_input_field_contract("gmail_create_draft", structured_only_field) == {
            "accepted_value_kinds": ["structured"]
        }


def test_validation_narrative_to_gmail_fields_table_driven():
    """Table-driven check: narrative binding is accepted for body_text/subject and rejected for others."""
    source_node = _node(
        "s1",
        "capability",
        {
            "capability_key": "specialist_agent",
            "target": {"agent_id": "a1"},
            "inputs": {"task": "generate text"},
        },
    )

    valid_fields = ["body_text", "subject"]
    invalid_fields = ["mode", "to", "cc", "bcc", "reply_to_message_id"]

    for field_name in valid_fields:
        inputs = {
            "mode": "new",
            "to": "test@example.com",
            "body_text": "default body",
            "subject": "default subject",
        }
        inputs[field_name] = _ref("nodes.s1.output.narrative.text")

        nodes = [
            source_node,
            _node("gm", "capability", {"capability_key": "gmail_create_draft", "inputs": inputs}),
            _node("done", "terminal", {"outcome": "success"}),
        ]
        edges = [_edge("e1", "s1", "gm"), _edge("e2", "gm", "done")]
        errors = _validate(nodes, edges)
        assert not errors, f"Field '{field_name}' should accept narrative, got errors: {errors}"

    for field_name in invalid_fields:
        inputs = {
            "mode": "new",
            "to": "test@example.com",
            "body_text": "default body",
            "subject": "default subject",
        }
        inputs[field_name] = _ref("nodes.s1.output.narrative.text")

        nodes = [
            source_node,
            _node("gm", "capability", {"capability_key": "gmail_create_draft", "inputs": inputs}),
            _node("done", "terminal", {"outcome": "success"}),
        ]
        edges = [_edge("e1", "s1", "gm"), _edge("e2", "gm", "done")]
        errors = _validate(nodes, edges)
        assert any("flow_contract:" in e for e in errors), f"Field '{field_name}' should reject narrative, but got errors: {errors}"


def test_validation_gmail_output_references_rejected():
    """All output fields of gmail_create_draft are forbidden from downstream references and conditions."""
    nodes = [
        _node(
            "gm",
            "capability",
            {
                "capability_key": "gmail_create_draft",
                "inputs": {
                    "mode": "new",
                    "to": "test@example.com",
                    "subject": "hello",
                    "body_text": "world",
                },
            },
        ),
        _node(
            "w",
            "capability",
            {
                "capability_key": "vault_write_file",
                "inputs": {
                    "relative_path": "out.md",
                    "content": _ref("nodes.gm.output.gmail_draft_id"),
                },
            },
        ),
        _node("done", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "gm", "w"), _edge("e2", "w", "done")]
    errors = _validate(nodes, edges)
    assert any("output_contract:" in e for e in errors), errors

    # Condition edge on gmail status is also forbidden
    cond_nodes = [
        _node(
            "gm",
            "capability",
            {
                "capability_key": "gmail_create_draft",
                "inputs": {
                    "mode": "new",
                    "to": "test@example.com",
                    "subject": "hello",
                    "body_text": "world",
                },
            },
        ),
        _node("ok", "terminal", {"outcome": "success"}),
        _node("ng", "terminal", {"outcome": "failure"}),
    ]
    cond_edges = [
        _edge(
            "e1",
            "gm",
            "ok",
            condition={
                "from_path": "nodes.gm.output.status",
                "operator": "equals",
                "value": "created",
            },
        ),
        _edge("e2", "gm", "ng"),
    ]
    cond_errors = _validate(cond_nodes, cond_edges)
    assert any("flow_contract" in e or "output_contract" in e for e in cond_errors), cond_errors


# --- 2. End-to-End Workflow Execution Test ---


def test_e2e_gmail_create_draft_pipeline(test_memory_db_path, monkeypatch):
    """Mixed narrative -> Text Template -> gmail_create_draft -> fake Gmail API.

    Verifies API is called exactly once and receipt is stored in DB.
    """
    mock_draft_create = MagicMock(
        return_value={"id": "draft_999", "message": {"id": "msg_999", "threadId": "th_999"}}
    )
    mock_service_res = MagicMock()
    mock_service_res.users().drafts().create.return_value.execute = mock_draft_create

    monkeypatch.setattr(GmailService, "_get_service", lambda self: mock_service_res)

    nodes = [
        _node(
            "tmpl1",
            "text_template",
            {
                "inputs": {},
                "template": "Hello from Workflow Text Template",
            },
        ),
        _node(
            "gm1",
            "capability",
            {
                "capability_key": "gmail_create_draft",
                "inputs": {
                    "mode": "new",
                    "to": "recipient@example.com",
                    "subject": "Notification Subject",
                    "body_text": _ref("nodes.tmpl1.output.text"),
                },
            },
        ),
        _node("done", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "tmpl1", "gm1"), _edge("e2", "gm1", "done")]

    wf = workflow_store.create_workflow("gmail-test-wf", skip_approval=True)
    rev = wf["revision"]
    workflow_store.set_revision_graph(rev["revision_id"], nodes, edges)
    workflow_store.publish_revision(rev["revision_id"])

    workflow_store.create_run(wf["workflow_id"], rev["revision_id"], {})
    run = workflow_store.claim_run("test-instance")
    assert run is not None

    outcome = WorkflowEngine(DefaultNodeRunner(poll_interval=0.01)).execute(run)
    assert outcome.kind == "completed"

    mock_create = mock_service_res.users().drafts().create
    assert mock_create.call_count == 1
    call_args = mock_create.call_args[1]
    assert call_args["userId"] == "me"
    assert call_args["body"]["message"]["raw"]

    # Verify receipt persisted in DB
    run_nodes = workflow_store.list_run_nodes(run["run_id"])
    gm1_node = next(n for n in run_nodes if n["node_id"] == "gm1")
    output = gm1_node["output"]

    assert output["status"] == "created"
    assert output["gmail_draft_id"] == "draft_999"
    assert output["gmail_message_id"] == "msg_999"
    assert output["gmail_thread_id"] == "th_999"
    assert output["reused_receipt"] is False
    assert output["receipt_persisted"] is True

    # Check gmail_draft_requests row directly
    db_rec = gmail_store.get_draft_request(output["request_key"])
    assert db_rec is not None
    assert db_rec["status"] == "created"
    assert db_rec["gmail_draft_id"] == "draft_999"


# --- 3. Idempotency & Attention Halt Tests ---


def test_gmail_adapter_receipt_reuse_no_second_api_call(test_memory_db_path, monkeypatch):
    """Re-executing the same action key with identical input hash reuses the stored receipt without calling Gmail API."""
    mock_draft_create = MagicMock(
        return_value={"id": "draft_777", "message": {"id": "msg_777", "threadId": "th_777"}}
    )
    mock_service_res = MagicMock()
    mock_service_res.users().drafts().create.return_value.execute = mock_draft_create
    monkeypatch.setattr(GmailService, "_get_service", lambda self: mock_service_res)

    task = {
        "task_id": "task_100",
        "workflow_run_id": "wfrun_100",
        "workflow_activation_id": "act_100",
    }
    plan = {"plan_id": "tplan_100"}
    step = {
        "capability_key": "gmail_create_draft",
        "inputs": {
            "mode": "new",
            "to": "user@example.com",
            "subject": "Hello",
            "body_text": "Body content",
        },
    }

    adapter = GmailDraftAdapter()

    # First call -> triggers API
    res1 = adapter.execute_step(task, plan, 0, step)
    assert res1.needs_attention is False
    assert res1.output["status"] == "created"
    assert res1.output["gmail_draft_id"] == "draft_777"
    assert res1.output["reused_receipt"] is False
    assert mock_draft_create.call_count == 1

    # Second call -> reuses receipt, Gmail API is NOT called again
    res2 = adapter.execute_step(task, plan, 0, step)
    assert res2.needs_attention is False
    assert res2.output["status"] == "created"
    assert res2.output["gmail_draft_id"] == "draft_777"
    assert res2.output["reused_receipt"] is True
    assert mock_draft_create.call_count == 1  # count stays 1


def test_gmail_adapter_input_hash_mismatch_halts_needs_attention(test_memory_db_path, monkeypatch):
    """Input hash mismatch for the same action key halts in needs_attention without calling Gmail API."""
    mock_draft_create = MagicMock(
        return_value={"id": "draft_555", "message": {"id": "msg_555", "threadId": "th_555"}}
    )
    mock_service_res = MagicMock()
    mock_service_res.users().drafts().create.return_value.execute = mock_draft_create
    monkeypatch.setattr(GmailService, "_get_service", lambda self: mock_service_res)

    task = {
        "task_id": "task_200",
        "workflow_run_id": "wfrun_200",
        "workflow_activation_id": "act_200",
    }
    plan = {"plan_id": "tplan_200"}
    step1 = {
        "capability_key": "gmail_create_draft",
        "inputs": {
            "mode": "new",
            "to": "user@example.com",
            "subject": "Original Subject",
            "body_text": "Body content",
        },
    }

    adapter = GmailDraftAdapter()
    res1 = adapter.execute_step(task, plan, 0, step1)
    assert res1.needs_attention is False
    assert mock_draft_create.call_count == 1

    # Same action key, modified inputs -> hash mismatch
    step2 = {
        "capability_key": "gmail_create_draft",
        "inputs": {
            "mode": "new",
            "to": "user@example.com",
            "subject": "MODIFIED Subject",
            "body_text": "Body content",
        },
    }

    res2 = adapter.execute_step(task, plan, 0, step2)
    assert res2.needs_attention is True
    assert res2.attention_reason == "input_hash_mismatch"
    assert mock_draft_create.call_count == 1  # API was NOT called second time
    assert "Input hash mismatch" in res2.error


def test_gmail_adapter_pending_or_unknown_halts_needs_attention(test_memory_db_path, monkeypatch):
    """Pending ('creating') or 'unknown' status halts in needs_attention without retrying."""
    mock_draft_create = MagicMock(side_effect=RuntimeError("Simulated network timeout during draft creation"))
    mock_service_res = MagicMock()
    mock_service_res.users().drafts().create.return_value.execute = mock_draft_create
    monkeypatch.setattr(GmailService, "_get_service", lambda self: mock_service_res)

    task = {
        "task_id": "task_300",
        "workflow_run_id": "wfrun_300",
        "workflow_activation_id": "act_300",
    }
    plan = {"plan_id": "tplan_300"}
    step = {
        "capability_key": "gmail_create_draft",
        "inputs": {
            "mode": "new",
            "to": "user@example.com",
            "subject": "Subject",
            "body_text": "Body",
        },
    }

    adapter = GmailDraftAdapter()

    # First attempt fails mid-dispatch -> unknown status
    res1 = adapter.execute_step(task, plan, 0, step)
    assert res1.needs_attention is True
    assert res1.attention_reason == "uncertain_outcome"
    assert res1.output["status"] == "unknown"

    # Second attempt with same action key -> blocked due to unknown status
    res2 = adapter.execute_step(task, plan, 0, step)
    assert res2.needs_attention is True
    assert res2.attention_reason == "pending_or_unknown_request"
    assert "Automatic re-execution blocked" in res2.error


def test_gmail_adapter_local_receipt_persistence_failure_halts_needs_attention(test_memory_db_path, monkeypatch):
    """If Gmail API call succeeds but local DB receipt persistence fails, halts in needs_attention with receipt_persisted=False."""
    mock_draft_create = MagicMock(
        return_value={"id": "draft_888", "message": {"id": "msg_888", "threadId": "th_888"}}
    )
    mock_service_res = MagicMock()
    mock_service_res.users().drafts().create.return_value.execute = mock_draft_create
    monkeypatch.setattr(GmailService, "_get_service", lambda self: mock_service_res)

    # Force mark_draft_request_created to throw a DB error
    def bad_mark_created(*args, **kwargs):
        raise RuntimeError("Simulated DB write failure")

    monkeypatch.setattr("obsidian_ai_hub.gmail.client.mark_draft_request_created", bad_mark_created)

    task = {
        "task_id": "task_400",
        "workflow_run_id": "wfrun_400",
        "workflow_activation_id": "act_400",
    }
    plan = {"plan_id": "tplan_400"}
    step = {
        "capability_key": "gmail_create_draft",
        "inputs": {
            "mode": "new",
            "to": "user@example.com",
            "subject": "Subject",
            "body_text": "Body",
        },
    }

    adapter = GmailDraftAdapter()
    res = adapter.execute_step(task, plan, 0, step)

    assert res.needs_attention is True
    assert res.attention_reason == "receipt_persistence_failed"
    assert res.output["gmail_draft_id"] == "draft_888"
    assert res.output["receipt_persisted"] is False
