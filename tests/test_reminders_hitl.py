from __future__ import annotations

import json
from unittest.mock import patch

from obsidian_ai_hub import hitl
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.handler import apple_reminders as apple_reminders_module
from obsidian_ai_hub.main import register_hitl_handlers
from obsidian_ai_hub.reminders import register_reminder_approval

REMINDER = {
    "title": "本の返却",
    "due_date": "2026-05-15T18:00:00",
}
CONTENT = "明日までに本を返す"

SUCCESS_RESULT = "Successfully added reminder: 本の返却"


def _reminder_runs(conn):
    from obsidian_ai_hub.hitl.store import list_runs

    runs, _ = list_runs(conn=conn)
    return [r for r in runs if r["handler"] == "reminders.add_approved_reminder"]


def test_register_reminder_approval_creates_pending_run(test_memory_db_path):
    run_id = register_reminder_approval(CONTENT, REMINDER)
    assert run_id is not None

    conn = get_db_connection()
    try:
        run = hitl.get_run(run_id, conn)
        assert run is not None
        assert run["handler"] == "reminders.add_approved_reminder"
        assert run["status"] == "pending_user"
        assert run["display_type"] == "リマインダー登録"
    finally:
        conn.close()


def test_register_reminder_approval_is_idempotent(test_memory_db_path):
    run_id_1 = register_reminder_approval(CONTENT, REMINDER)
    run_id_2 = register_reminder_approval(CONTENT, REMINDER)
    assert run_id_1 == run_id_2

    conn = get_db_connection()
    try:
        assert len(_reminder_runs(conn)) == 1
    finally:
        conn.close()


def test_register_same_content_different_due_date_gets_distinct_runs(
    test_memory_db_path,
):
    other_reminder = {**REMINDER, "due_date": "2026-05-16T18:00:00"}
    run_id_1 = register_reminder_approval(CONTENT, REMINDER)
    run_id_2 = register_reminder_approval(CONTENT, other_reminder)
    assert run_id_1 != run_id_2

    conn = get_db_connection()
    try:
        assert len(_reminder_runs(conn)) == 2
        first = hitl.get_run(run_id_1, conn)
        second = hitl.get_run(run_id_2, conn)
        assert (
            json.loads(first["checkpoint"])["reminder"]["due_date"]
            == REMINDER["due_date"]
        )
        assert (
            json.loads(second["checkpoint"])["reminder"]["due_date"]
            == other_reminder["due_date"]
        )
    finally:
        conn.close()


def test_dispatch_approve_adds_reminder(test_memory_db_path):
    register_hitl_handlers()
    run_id = register_reminder_approval(CONTENT, REMINDER)

    conn = get_db_connection()
    try:
        hitl.submit_answer(run_id, "confirm_reminder", "action", "approve", conn)
        with patch.object(apple_reminders_module, "add_reminder") as mock_tool:
            mock_tool.invoke.return_value = SUCCESS_RESULT
            processed = hitl.dispatch_runs(conn)
        assert processed == 1
        mock_tool.invoke.assert_called_once_with(
            {
                "title": "本の返却",
                "due_date": "2026-05-15T18:00:00",
            }
        )
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "completed"
        assert '"phase": "added"' in run["checkpoint"]
    finally:
        conn.close()


def test_reregister_after_completion_does_not_readd_reminder(test_memory_db_path):
    register_hitl_handlers()
    run_id = register_reminder_approval(CONTENT, REMINDER)

    conn = get_db_connection()
    try:
        hitl.submit_answer(run_id, "confirm_reminder", "action", "approve", conn)
        with patch.object(apple_reminders_module, "add_reminder") as mock_tool:
            mock_tool.invoke.return_value = SUCCESS_RESULT
            hitl.dispatch_runs(conn)

        # A repeated inbox merge re-registers the same deterministic run_id.
        re_registered = register_reminder_approval(CONTENT, REMINDER)
        assert re_registered == run_id

        with patch.object(apple_reminders_module, "add_reminder") as mock_tool:
            processed = hitl.dispatch_runs(conn)
        assert processed == 0
        mock_tool.invoke.assert_not_called()

        run = hitl.get_run(run_id, conn)
        assert run["status"] == "completed"
        assert '"phase": "added"' in run["checkpoint"]
    finally:
        conn.close()


def test_dispatch_decline_skips_reminder_add(test_memory_db_path):
    register_hitl_handlers()
    run_id = register_reminder_approval(CONTENT, REMINDER)

    conn = get_db_connection()
    try:
        hitl.submit_answer(run_id, "confirm_reminder", "action", "decline", conn)
        with patch.object(apple_reminders_module, "add_reminder") as mock_tool:
            processed = hitl.dispatch_runs(conn)
        assert processed == 1
        mock_tool.invoke.assert_not_called()
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "completed"
        assert '"phase": "declined"' in run["checkpoint"]
    finally:
        conn.close()


def test_dispatch_approve_tool_failure_marks_run_failed(test_memory_db_path):
    register_hitl_handlers()
    run_id = register_reminder_approval(CONTENT, REMINDER)

    conn = get_db_connection()
    try:
        hitl.submit_answer(run_id, "confirm_reminder", "action", "approve", conn)
        with patch.object(apple_reminders_module, "add_reminder") as mock_tool:
            mock_tool.invoke.return_value = "Failed to add reminder: boom"
            processed = hitl.dispatch_runs(conn)
        assert processed == 1
        mock_tool.invoke.assert_called_once()
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "failed"
        assert "Failed to add reminder" in run["error_message"]
    finally:
        conn.close()


def test_handler_fails_loudly_on_unexpected_answer(test_memory_db_path):
    from obsidian_ai_hub.hitl.dispatcher import HitlContext
    from obsidian_ai_hub.reminders.hitl import add_approved_reminder

    conn = get_db_connection()
    try:
        checkpoint = json.dumps(
            {
                "type": "reminder",
                "reminder": REMINDER,
                "content": CONTENT,
                "phase": "awaiting_approval",
            }
        )
        ctx = HitlContext(
            run_id="hrun_test_unexpected",
            checkpoint=checkpoint,
            answers_by_question_key={"action": "maybe"},
            conn=conn,
            raw_answers_by_question_key={"action": {"value": "maybe", "comment": None}},
        )
        result = add_approved_reminder(ctx)
        assert result.status == "failed"
        assert "Unexpected action answer" in result.error_message
    finally:
        conn.close()


def test_handler_skips_when_already_added(test_memory_db_path):
    from obsidian_ai_hub.hitl.dispatcher import HitlContext
    from obsidian_ai_hub.reminders.hitl import add_approved_reminder

    conn = get_db_connection()
    try:
        checkpoint = json.dumps(
            {
                "type": "reminder",
                "reminder": REMINDER,
                "content": CONTENT,
                "phase": "added",
            }
        )
        ctx = HitlContext(
            run_id="hrun_test_added",
            checkpoint=checkpoint,
            answers_by_question_key={"action": "approve"},
            conn=conn,
            raw_answers_by_question_key={
                "action": {"value": "approve", "comment": None}
            },
        )
        with patch.object(apple_reminders_module, "add_reminder") as mock_tool:
            result = add_approved_reminder(ctx)
        assert result.status == "completed"
        mock_tool.invoke.assert_not_called()
    finally:
        conn.close()
