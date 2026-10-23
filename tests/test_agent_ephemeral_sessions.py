"""Ephemeral (temporary) agent conversations: retention boundaries.

Operation scenario (docs/development-quality-playbook.md): a user opens a
temporary conversation, chats (messages + runs + LLM calls happen), then ends
it or lets the TTL sweeper collect it. Afterwards nothing remains: no session
row, no messages/runs/events (FK cascade), no LLM call logs (suppressed at
write time because they have no cascade), no memory candidates, no search
hits, no notifications.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub import memory
from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils import execution_logger
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def auth_headers(api_token):
    return {"Authorization": f"Bearer {api_token}"}


@pytest.fixture
def client(api_token):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app)


def _make_agent(name="ephemeral-agent"):
    return agent_store.create_agent(
        name=f"{name} {uuid.uuid4().hex[:8]}", system_prompt="prompt"
    )


def test_migration_v80_adds_is_ephemeral_column(test_memory_db_path):
    conn = get_db_connection()
    try:
        version = conn.execute("PRAGMA user_version;").fetchone()[0]
        assert version >= 80
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(agent_sessions);")}
        assert "is_ephemeral" in cols
    finally:
        conn.close()


def test_create_ephemeral_session_hidden_from_list_but_readable(test_memory_db_path):
    agent = _make_agent()
    normal = agent_store.create_session(agent["agent_id"], title="通常")
    ephemeral = agent_store.create_session(
        agent["agent_id"], title="一時", ephemeral=True
    )

    assert ephemeral["is_ephemeral"] is True
    assert normal["is_ephemeral"] is False

    listed = agent_store.list_sessions(agent["agent_id"])
    assert {s["session_id"] for s in listed} == {normal["session_id"]}

    # Detail view still works during the TTL window.
    fetched = agent_store.get_session(ephemeral["session_id"])
    assert fetched is not None and fetched["is_ephemeral"] is True


def test_search_and_memory_extraction_exclude_ephemeral(test_memory_db_path):
    agent = _make_agent(name="ephemeral-search-agent")
    eph = agent_store.create_session(agent["agent_id"], ephemeral=True)
    agent_store.start_queued_run(eph["session_id"], "一時の秘密の合言葉そらまめ")
    normal = agent_store.create_session(agent["agent_id"])
    agent_store.start_queued_run(normal["session_id"], "通常の合言葉そらまめ")

    results = agent_store.search_messages("そらまめ")
    assert {r["session_id"] for r in results} == {normal["session_id"]}

    from datetime import date

    from zoneinfo import ZoneInfo

    today_jst = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    overviews = agent_store.list_daily_session_overviews(today_jst)
    titles = [o["session_title"] for o in overviews]
    assert "一時" not in titles


def test_load_weekly_agent_messages_excludes_ephemeral(test_memory_db_path):
    from datetime import timezone as _tz, timedelta as _td

    agent = _make_agent(name="ephemeral-extract-agent")
    eph = agent_store.create_session(agent["agent_id"], title="一時の会話", ephemeral=True)
    normal = agent_store.create_session(agent["agent_id"], title="通常の会話")

    conn = get_db_connection()
    try:
        with conn:
            for sid, content in (
                (eph["session_id"], "一時の発話"),
                (normal["session_id"], "通常の発話"),
            ):
                conn.execute(
                    "INSERT INTO agent_messages (message_id, session_id, sequence, role, content, created_at)"
                    " VALUES (?, ?, 1, 'user', ?, ?)",
                    (
                        f"amsg_{uuid.uuid4().hex[:12]}",
                        sid,
                        content,
                        "2026-07-14T01:00:00+00:00",
                    ),
                )
    finally:
        conn.close()

    week_start, week_end = memory._week_bounds("2026-07-13")
    sessions, included = memory._load_weekly_agent_messages(week_start, week_end)
    assert [s["session_id"] for s in sessions] == [normal["session_id"]]
    assert all("一時の発話" not in (e.get("content") or "") for s in sessions for e in s["entries"])


def test_ephemeral_runs_do_not_publish_notifications(test_memory_db_path):
    agent = _make_agent(name="ephemeral-notify-agent")
    eph = agent_store.create_session(agent["agent_id"], ephemeral=True)
    _, eph_run = agent_store.start_queued_run(eph["session_id"], "hello")
    normal = agent_store.create_session(agent["agent_id"])
    _, normal_run = agent_store.start_queued_run(normal["session_id"], "hello")

    with patch(
        "obsidian_ai_hub.notifications.publish_notification"
    ) as mock_publish:
        agent_store.update_run_hitl(eph_run["run_id"], "waiting_user")
        assert mock_publish.call_count == 0
        agent_store.update_run_hitl(normal_run["run_id"], "waiting_user")
        assert mock_publish.call_count == 1


def test_execution_logging_suppression_context(test_memory_db_path):
    token = execution_logger.suppress_execution_logging()
    try:
        assert execution_logger.execution_logging_suppressed() is True
        execution_logger.start_llm_call("suppressed-call", None, "p", "m", 0.0, 10, "q")
        execution_logger.succeed_llm_call("suppressed-call", "r", 1, 1, 2, "stop")
        execution_logger.fail_llm_call("suppressed-fail", RuntimeError("x"))
        execution_logger.update_llm_call_tool_calls("suppressed-call", [])
    finally:
        execution_logger.reset_execution_logging(token)

    assert execution_logger.execution_logging_suppressed() is False
    items, _ = execution_logger.list_execution_logs()
    assert "suppressed-call" not in {i["id"] for i in items}

    execution_logger.start_llm_call("kept-call", None, "p", "m", 0.0, 10, "q")
    items, _ = execution_logger.list_execution_logs()
    assert "kept-call" in {i["id"] for i in items}


def _backdate_session_updated_at(session_id, *, hours_ago):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE agent_sessions SET updated_at = ? WHERE session_id = ?;",
            (cutoff, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_purge_ephemeral_sessions_ttl(test_memory_db_path):
    agent = _make_agent(name="ephemeral-purge-agent")
    old_idle = agent_store.create_session(agent["agent_id"], ephemeral=True)
    _backdate_session_updated_at(old_idle["session_id"], hours_ago=25)
    recent = agent_store.create_session(agent["agent_id"], ephemeral=True)
    old_normal = agent_store.create_session(agent["agent_id"])
    _backdate_session_updated_at(old_normal["session_id"], hours_ago=25)

    # Messages do not protect ephemeral sessions from TTL purge.
    # Note: sending refreshes updated_at, so backdate after the turn.
    agent_store.start_queued_run(old_idle["session_id"], "uses")
    _backdate_session_updated_at(old_idle["session_id"], hours_ago=25)

    removed = agent_store.purge_ephemeral_sessions(ttl_hours=24)
    assert removed == 1
    assert agent_store.get_session(old_idle["session_id"]) is None
    assert agent_store.get_session(recent["session_id"]) is not None
    assert agent_store.get_session(old_normal["session_id"]) is not None


def test_cleanup_old_logs_now_includes_ephemeral(test_memory_db_path):
    agent = _make_agent(name="ephemeral-cleanup-agent")
    old_idle = agent_store.create_session(agent["agent_id"], ephemeral=True)
    _backdate_session_updated_at(old_idle["session_id"], hours_ago=25)

    result = execution_logger.cleanup_old_logs_now(days=30)
    assert result["ephemeral_agent_sessions"] == 1
    assert agent_store.get_session(old_idle["session_id"]) is None


@pytest.mark.anyio
async def test_worker_suppresses_llm_logs_for_ephemeral_runs(test_memory_db_path):
    from obsidian_ai_hub.runs import agent_worker

    agent = _make_agent(name="ephemeral-worker-agent")
    eph = agent_store.create_session(agent["agent_id"], ephemeral=True)
    _, run = agent_store.start_queued_run(eph["session_id"], "hello worker")

    llm_calls: list[str] = []

    async def fake_stream(**kwargs):
        assert execution_logger.execution_logging_suppressed() is True
        execution_logger.start_llm_call("worker-call", run["run_id"], "p", "m", 0.0, 10, "q")
        execution_logger.succeed_llm_call("worker-call", "r", 1, 1, 2, "stop")
        llm_calls.append("worker-call")
        from obsidian_ai_hub.agents import store as _store

        _store.complete_run(run["run_id"], "done reply")
        yield 'data: {"type": "done", "run_id": "%s"}' % run["run_id"]

    with patch(
        "obsidian_ai_hub.agents.runtime.generate_agent_stream",
        side_effect=fake_stream,
    ):
        await agent_worker.execute_agent_run(run["run_id"])

    assert llm_calls == ["worker-call"]
    items, _ = execution_logger.list_execution_logs()
    assert "worker-call" not in {i["id"] for i in items}
    assert execution_logger.execution_logging_suppressed() is False
    # Conversation rows still exist until explicit end/TTL.
    assert agent_store.get_session(eph["session_id"]) is not None


def test_ephemeral_end_to_end_delete_removes_everything(test_memory_db_path):
    """Playbook scenario: chat in an ephemeral session, then end it by delete."""
    agent = _make_agent(name="ephemeral-e2e-agent")
    eph = agent_store.create_session(agent["agent_id"], ephemeral=True)
    msg, run = agent_store.start_user_run(eph["session_id"], "hello")
    agent_store.complete_run(run["run_id"], "hi there")

    assert len(agent_store.list_messages(eph["session_id"])) == 2
    assert len(agent_store.list_runs(eph["session_id"])) == 1

    assert agent_store.delete_session(eph["session_id"]) is True

    assert agent_store.get_session(eph["session_id"]) is None
    assert agent_store.list_messages(eph["session_id"]) == []
    assert agent_store.list_runs(eph["session_id"]) == []
    assert agent_store.search_messages("hello") == []


def test_ephemeral_session_api_flow(client, auth_headers, test_memory_db_path):
    res = client.post(
        "/api/v1/agents",
        json={"name": "Ephemeral API", "system_prompt": "p"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    agent_id = res.json()["agent"]["agent_id"]

    res = client.post(
        f"/api/v1/agents/{agent_id}/sessions",
        json={"ephemeral": True},
        headers=auth_headers,
    )
    assert res.status_code == 201
    session = res.json()["session"]
    assert session["is_ephemeral"] is True

    res = client.get(f"/api/v1/agents/{agent_id}/sessions", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["sessions"] == []

    res = client.get(
        f"/api/v1/agent-sessions/{session['session_id']}", headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["session"]["is_ephemeral"] is True

    res = client.delete(
        f"/api/v1/agent-sessions/{session['session_id']}", headers=auth_headers
    )
    assert res.status_code == 200
