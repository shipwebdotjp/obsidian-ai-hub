from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from obsidian_ai_hub import database, hitl
from obsidian_ai_hub.notifications import store as notif_store
from obsidian_ai_hub.notifications import publisher
from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.workflow import store as wf_store
from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.coding import store as coding_store
from obsidian_ai_hub.planner import suggest as planner_suggest


def test_notification_delivery_matrix_and_commit_behavior(tmp_path, monkeypatch):
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    published_events = []

    def mock_publish(event):
        published_events.append(event)
        return True

    monkeypatch.setattr("obsidian_ai_hub.notifications.publish_notification", mock_publish)
    monkeypatch.setattr("obsidian_ai_hub.notifications.publisher.publish_notification", mock_publish)

    # 1. HITL: pending_user triggers notification
    hitl.register_run_and_questions(
        run_id="hrun_test_1",
        handler="dummy",
        checkpoint="chk",
        question_set_id="qset_1",
        questions_data=[
            {"question_key": "q1", "question_type": "text", "display_text": "Need answer", "is_required": 1}
        ],
        display_type="タスク確認",
        title="テストHITLタイトル",
    )

    assert len(published_events) == 1
    ev = published_events[-1]
    assert ev.event_type == "hitl"
    assert ev.category == "action_required"
    assert "テストHITLタイトル" in ev.body or "タスク確認" in ev.title

    # Duplicate registration for same question set does not resend
    hitl.register_run_and_questions(
        run_id="hrun_test_1",
        handler="dummy",
        checkpoint="chk",
        question_set_id="qset_1",
        questions_data=[
            {"question_key": "q1", "question_type": "text", "display_text": "Need answer", "is_required": 1}
        ],
        display_type="タスク確認",
        title="テストHITLタイトル",
    )
    assert len(published_events) == 1


def test_task_agent_parent_only_and_success_cancel_exclusion(tmp_path, monkeypatch):
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    published_events = []

    def mock_publish(event):
        published_events.append(event)
        return True

    monkeypatch.setattr("obsidian_ai_hub.notifications.publish_notification", mock_publish)
    monkeypatch.setattr("obsidian_ai_hub.notifications.publisher.publish_notification", mock_publish)

    # User task (parent)
    task = task_store.create_task("User task prompt", origin="user")
    task_id = task["task_id"]

    # Transition to planning -> waiting_approval
    task_store.claim_task("worker_1", "planning")
    task_store.create_plan(task_id, {"steps": []}, {})
    task_store.transition_task_status(task_id, "waiting_approval")

    assert len(published_events) == 1
    assert published_events[-1].category == "action_required"

    # Approve task -> ready -> running -> completed (Success: NO notification)
    task_store.decide_plan(task_id, "approve")
    task_store.claim_task("worker_1", "execution")
    task_store.transition_task_status(task_id, "completed")

    # Success should not trigger additional notification
    assert len(published_events) == 1

    # Workflow task (child bridge): should NOT send notifications
    wf_task = task_store.create_task("Workflow bridge task", origin="workflow")
    wf_task_id = wf_task["task_id"]
    task_store.claim_task("worker_1", "planning")
    task_store.create_plan(wf_task_id, {"steps": []}, {})
    task_store.transition_task_status(wf_task_id, "waiting_approval")

    # Should stay at 1 because workflow bridge task is excluded
    assert len(published_events) == 1


def test_workflow_and_agent_failure_and_ask_user_suppression(tmp_path, monkeypatch):
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    published_events = []

    def mock_publish(event):
        published_events.append(event)
        return True

    monkeypatch.setattr("obsidian_ai_hub.notifications.publish_notification", mock_publish)
    monkeypatch.setattr("obsidian_ai_hub.notifications.publisher.publish_notification", mock_publish)

    # 1. Agent run ask_user (waiting_user)
    agent = agent_store.create_agent("TestAgent", "System prompt")
    session = agent_store.create_session(agent["agent_id"], title="テスト対話")
    msg, run = agent_store.start_user_run(session["session_id"], "User prompt")
    run_id = run["run_id"]

    agent_store.update_run_hitl(run_id, "waiting_user")
    assert len(published_events) == 1
    assert published_events[-1].event_type == "agent"
    assert published_events[-1].category == "action_required"

    # Agent ask_user registers an in_conversation_question HITL run: should be suppressed
    hitl.register_run_and_questions(
        run_id="hrun_ask_user_1",
        handler="agents.ask_user",
        checkpoint=json.dumps({"domain": "agent", "run_id": run_id}),
        question_set_id="qs1",
        questions_data=[{"question_key": "q", "question_type": "text", "display_text": "q", "is_required": 1}],
        display_type="in_conversation_question",
        title="Agent question",
    )
    # Event count must remain 1 because in_conversation_question is suppressed in HITL
    assert len(published_events) == 1

    # 2. Agent run failure
    agent_store.transition_run_status(run_id, "failed", finished=True)
    assert len(published_events) == 2
    assert published_events[-1].category == "failure"


def test_adapter_failure_does_not_fail_domain_task(tmp_path, monkeypatch):
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    # Enable Web Push & LINE in settings
    notif_store.update_notification_settings(
        web_push_enabled=True,
        web_push_action_required=True,
        line_enabled=True,
        line_action_required=True,
    )

    # Simulate an unexpected channel failure at the publisher boundary.
    def mock_line_error(*args, **kwargs):
        raise RuntimeError("LINE API unreachable")

    monkeypatch.setattr(
        "obsidian_ai_hub.notifications.publisher.send_line_push_result",
        mock_line_error,
    )

    # Create task and transition to waiting_approval
    task = task_store.create_task("Fault tolerance test task")
    task_id = task["task_id"]
    task_store.claim_task("worker_1", "planning")
    task_store.create_plan(task_id, {"steps": []}, {})

    # Status transition should succeed without raising, despite adapter exceptions
    updated = task_store.transition_task_status(task_id, "waiting_approval")
    assert updated["status"] == "waiting_approval"
