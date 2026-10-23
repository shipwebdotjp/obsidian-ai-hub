"""Empty Web-chat session cleanup: store predicates + CLI integration."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch

from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.utils import execution_logger


def _make_agent(name="cleanup-agent"):
    return agent_store.create_agent(name=name, system_prompt="prompt")


def _backdate_session(session_id, *, days_ago=2, jst_hour=12):
    """Set created_at to a JST wall time `days_ago` before today."""
    jst_today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    target_jst = datetime(
        jst_today.year, jst_today.month, jst_today.day, jst_hour, 0, 0,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    ) - timedelta(days=days_ago)
    target_utc = target_jst.astimezone(timezone.utc).isoformat()
    # agent store uses obsidian_ai_hub.database.get_db_connection
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE agent_sessions SET created_at = ?, updated_at = ? WHERE session_id = ?;",
            (target_utc, target_utc, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def _make_session(agent_id, *, title=None, source="chat"):
    kwargs = {"title": title} if title is not None else {}
    return agent_store.create_session(agent_id, source=source, **kwargs)


def test_purge_deletes_only_old_untouched_chat_sessions(test_memory_db_path):
    agent = _make_agent()

    old_empty = _make_session(agent["agent_id"])
    _backdate_session(old_empty["session_id"], days_ago=2)

    today_empty = _make_session(agent["agent_id"])
    # created just now -> JST today -> kept
    assert agent_store.get_session(today_empty["session_id"]) is not None

    old_with_message = _make_session(agent["agent_id"])
    _backdate_session(old_with_message["session_id"], days_ago=2)
    agent_store.start_queued_run(old_with_message["session_id"], "hello")
    # First user turn auto-retitles the session; restore the default title so
    # the message exclusion (not the title filter) is what retains this row.
    agent_store.update_session(
        old_with_message["session_id"], title=agent_store.EMPTY_CHAT_SESSION_TITLE
    )

    # Note: a run without any message cannot be constructed under the FK
    # enforcement (deleting the message cascades to the run), so the runs
    # predicate in the DELETE stays as a defensive second guard; the
    # message-bearing session above proves the DELETE rechecks exclusions
    # instead of trusting the candidate SELECT.

    old_renamed = _make_session(agent["agent_id"])
    _backdate_session(old_renamed["session_id"], days_ago=2)
    agent_store.update_session(old_renamed["session_id"], title="相談メモ")

    old_task = _make_session(agent["agent_id"], source="task")
    _backdate_session(old_task["session_id"], days_ago=2)
    old_workflow = _make_session(agent["agent_id"], source="workflow")
    _backdate_session(old_workflow["session_id"], days_ago=2)

    removed = agent_store.purge_empty_chat_sessions()

    assert removed == 1
    assert agent_store.get_session(old_empty["session_id"]) is None
    assert agent_store.get_session(today_empty["session_id"]) is not None
    assert agent_store.get_session(old_with_message["session_id"]) is not None
    assert agent_store.get_session(old_renamed["session_id"]) is not None
    assert agent_store.get_session(old_task["session_id"]) is not None
    assert agent_store.get_session(old_workflow["session_id"]) is not None


def test_purge_does_not_exclude_pinned_sessions(test_memory_db_path):
    agent = _make_agent(name="cleanup-pinned-agent")
    sess = _make_session(agent["agent_id"])
    _backdate_session(sess["session_id"], days_ago=2)
    agent_store.update_session(sess["session_id"], pinned_at=datetime.now(timezone.utc).isoformat())

    assert agent_store.purge_empty_chat_sessions() == 1
    assert agent_store.get_session(sess["session_id"]) is None


def test_purge_uses_jst_date_boundary_not_elapsed_time(test_memory_db_path):
    agent = _make_agent(name="cleanup-jst-agent")
    sess = _make_session(agent["agent_id"])
    # JST yesterday 23:59 -> eligible even though < 24h may have passed
    jst = ZoneInfo("Asia/Tokyo")
    now_jst = datetime.now(jst)
    yesterday_late_jst = (now_jst.replace(hour=23, minute=59, second=0, microsecond=0) - timedelta(days=1))
    # Guard: if today JST 00:00 is in the future relative to this computed time, keep as-is
    target_utc = yesterday_late_jst.astimezone(timezone.utc).isoformat()
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE agent_sessions SET created_at = ?, updated_at = ? WHERE session_id = ?;",
            (target_utc, target_utc, sess["session_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    assert agent_store.purge_empty_chat_sessions() == 1
    assert agent_store.get_session(sess["session_id"]) is None


def test_cleanup_old_logs_now_includes_empty_sessions(test_memory_db_path):
    agent = _make_agent(name="cleanup-logs-agent")
    old_empty = _make_session(agent["agent_id"])
    _backdate_session(old_empty["session_id"], days_ago=2)

    old_time = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO command_runs (run_id, command, args_json, started_at, status) VALUES (?, ?, ?, ?, 'succeeded')",
            ("old-run-cleanup", "old-cmd", "{}", old_time),
        )
        conn.commit()
    finally:
        conn.close()

    result = execution_logger.cleanup_old_logs_now(days=30)

    assert result["command_runs"] >= 1
    assert result["empty_agent_sessions"] == 1
    assert agent_store.get_session(old_empty["session_id"]) is None


def test_cleanup_old_logs_failure_does_not_rollback_logs(test_memory_db_path):
    old_time = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO command_runs (run_id, command, args_json, started_at, status) VALUES (?, ?, ?, ?, 'succeeded')",
            ("old-run-fail", "old-cmd", "{}", old_time),
        )
        conn.commit()
    finally:
        conn.close()

    import pytest

    with patch(
        "obsidian_ai_hub.agents.store.purge_empty_chat_sessions",
        side_effect=RuntimeError("purge boom"),
    ):
        with pytest.raises(RuntimeError, match="purge boom"):
            execution_logger.cleanup_old_logs_now(days=30)

    # Log cleanup committed before the purge failure.
    items, _ = execution_logger.list_execution_logs()
    assert "old-run-fail" not in {item["id"] for item in items}


def test_cli_cleanup_execution_logs_removes_empty_sessions(test_memory_db_path, monkeypatch):
    import sys

    import obsidian_ai_hub.main as main_module

    agent = _make_agent(name="cli-cleanup-agent")
    old_empty = _make_session(agent["agent_id"])
    _backdate_session(old_empty["session_id"], days_ago=2)

    monkeypatch.setattr(sys, "argv", ["prog", "--cleanup-execution-logs"])
    main_module.main()

    assert agent_store.get_session(old_empty["session_id"]) is None
    items, _ = execution_logger.list_execution_logs(kind="command")
    cleanup_runs = [i for i in items if i["name"] == "cleanup_execution_logs"]
    assert cleanup_runs and cleanup_runs[0]["status"] == "succeeded"
