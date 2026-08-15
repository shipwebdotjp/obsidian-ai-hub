from __future__ import annotations

import json
from unittest.mock import patch

from obsidian_ai_hub import hitl
from obsidian_ai_hub.calendar import register_calendar_event_approval
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.handler import add_calendar_event as add_calendar_event_module
from obsidian_ai_hub.main import register_hitl_handlers
from obsidian_ai_hub.utils import config

EVENT = {
    "title": "歯医者",
    "start_time": "2026-05-10T14:00:00",
    "end_time": "2026-05-10T15:00:00",
    "location": "駅前クリニック",
}
CONTENT = "明日14時から歯医者"

SUCCESS_RESULT = (
    "Successfully added event '歯医者' to calendar 'Default' "
    "from 2026-05-10 14:00:00 to 2026-05-10 15:00:00."
)


def _calendar_runs(conn):
    from obsidian_ai_hub.hitl.store import list_runs

    runs, _ = list_runs(conn=conn)
    return [r for r in runs if r["handler"] == "calendar.add_approved_event"]


def test_register_calendar_event_approval_creates_pending_run(test_memory_db_path):
    run_id = register_calendar_event_approval(CONTENT, EVENT)
    assert run_id is not None

    conn = get_db_connection()
    try:
        run = hitl.get_run(run_id, conn)
        assert run is not None
        assert run["handler"] == "calendar.add_approved_event"
        assert run["status"] == "pending_user"
        assert run["display_type"] == "カレンダー登録"
    finally:
        conn.close()


def test_register_calendar_event_approval_is_idempotent(test_memory_db_path):
    run_id_1 = register_calendar_event_approval(CONTENT, EVENT)
    run_id_2 = register_calendar_event_approval(CONTENT, EVENT)
    assert run_id_1 == run_id_2

    conn = get_db_connection()
    try:
        assert len(_calendar_runs(conn)) == 1
    finally:
        conn.close()


def test_register_same_content_different_event_gets_distinct_runs(test_memory_db_path):
    other_event = {**EVENT, "start_time": "2026-05-11T10:00:00"}
    run_id_1 = register_calendar_event_approval(CONTENT, EVENT)
    run_id_2 = register_calendar_event_approval(CONTENT, other_event)
    assert run_id_1 != run_id_2

    conn = get_db_connection()
    try:
        assert len(_calendar_runs(conn)) == 2
        first = hitl.get_run(run_id_1, conn)
        second = hitl.get_run(run_id_2, conn)
        assert json.loads(first["checkpoint"])["event"]["start_time"] == EVENT[
            "start_time"
        ]
        assert json.loads(second["checkpoint"])["event"]["start_time"] == other_event[
            "start_time"
        ]
    finally:
        conn.close()


def test_dispatch_approve_adds_calendar_event(test_memory_db_path, monkeypatch):
    register_hitl_handlers()
    monkeypatch.setattr(config, "APPLE_CALENDAR_NAME", "Work")
    run_id = register_calendar_event_approval(CONTENT, EVENT)

    conn = get_db_connection()
    try:
        hitl.submit_answer(run_id, "confirm_calendar", "action", "approve", conn)
        with patch.object(
            add_calendar_event_module, "add_calendar_event"
        ) as mock_tool:
            mock_tool.invoke.return_value = SUCCESS_RESULT
            processed = hitl.dispatch_runs(conn)
        assert processed == 1
        mock_tool.invoke.assert_called_once_with(
            {
                "title": "歯医者",
                "start_time": "2026-05-10T14:00:00",
                "end_time": "2026-05-10T15:00:00",
                "location": "駅前クリニック",
                "calendar_name": "Work",
            }
        )
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "completed"
        assert '"phase": "added"' in run["checkpoint"]
    finally:
        conn.close()


def test_dispatch_decline_skips_calendar_add(test_memory_db_path):
    register_hitl_handlers()
    run_id = register_calendar_event_approval(CONTENT, EVENT)

    conn = get_db_connection()
    try:
        hitl.submit_answer(run_id, "confirm_calendar", "action", "decline", conn)
        with patch.object(
            add_calendar_event_module, "add_calendar_event"
        ) as mock_tool:
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
    run_id = register_calendar_event_approval(CONTENT, EVENT)

    conn = get_db_connection()
    try:
        hitl.submit_answer(run_id, "confirm_calendar", "action", "approve", conn)
        with patch.object(
            add_calendar_event_module, "add_calendar_event"
        ) as mock_tool:
            mock_tool.invoke.return_value = "Failed to add calendar event: boom"
            processed = hitl.dispatch_runs(conn)
        assert processed == 1
        mock_tool.invoke.assert_called_once()
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "failed"
        assert "Failed to add calendar event" in run["error_message"]
    finally:
        conn.close()


def test_handler_fails_loudly_on_unexpected_answer(test_memory_db_path):
    from obsidian_ai_hub.calendar.hitl import add_approved_calendar_event
    from obsidian_ai_hub.hitl.dispatcher import HitlContext

    conn = get_db_connection()
    try:
        checkpoint = json.dumps(
            {
                "type": "calendar_event",
                "event": EVENT,
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
        result = add_approved_calendar_event(ctx)
        assert result.status == "failed"
        assert "Unexpected action answer" in result.error_message
    finally:
        conn.close()


def test_handler_skips_when_already_added(test_memory_db_path):
    from obsidian_ai_hub.calendar.hitl import add_approved_calendar_event
    from obsidian_ai_hub.hitl.dispatcher import HitlContext

    conn = get_db_connection()
    try:
        checkpoint = json.dumps(
            {
                "type": "calendar_event",
                "event": EVENT,
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
        with patch.object(
            add_calendar_event_module, "add_calendar_event"
        ) as mock_tool:
            result = add_approved_calendar_event(ctx)
        assert result.status == "completed"
        mock_tool.invoke.assert_not_called()
    finally:
        conn.close()