import pytest
from obsidian_ai_hub.agents import store
from obsidian_ai_hub.database import get_db_connection


def test_migration_v21_schema():
    conn = get_db_connection()
    cursor = conn.execute("PRAGMA user_version;")
    version = cursor.fetchone()[0]
    assert version >= 21

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('agents', 'agent_sessions', 'agent_messages', 'agent_runs');"
    )
    tables = {row[0] for row in cursor.fetchall()}
    assert tables == {"agents", "agent_sessions", "agent_messages", "agent_runs"}


def test_agent_crud_and_validation():
    # Validation errors
    with pytest.raises(ValueError, match="must not be empty"):
        store.create_agent(name="  ", system_prompt="Test prompt")

    with pytest.raises(ValueError, match="must not be empty"):
        store.create_agent(name="Test Agent", system_prompt="")

    # Creation
    agent = store.create_agent(
        name="Test Agent",
        system_prompt="You are a helpful assistant.",
        tool_ids=["web_search", "calendar_read"],
        provider="openai",
        model="gpt-4o",
    )
    assert agent["name"] == "Test Agent"
    assert agent["system_prompt"] == "You are a helpful assistant."
    assert agent["tool_ids"] == ["web_search", "calendar_read"]
    assert agent["provider"] == "openai"
    assert agent["model"] == "gpt-4o"

    # Duplicate name check
    with pytest.raises(ValueError, match="already exists"):
        store.create_agent(name="Test Agent", system_prompt="Other prompt")

    # Get & List
    fetched = store.get_agent(agent["agent_id"])
    assert fetched == agent

    all_agents = store.list_agents()
    assert len(all_agents) >= 1
    assert any(a["agent_id"] == agent["agent_id"] for a in all_agents)

    # Update
    updated = store.update_agent(
        agent["agent_id"],
        name="Updated Agent",
        tool_ids=["vault_search"],
        provider="",
    )
    assert updated["name"] == "Updated Agent"
    assert updated["tool_ids"] == ["vault_search"]
    assert updated["provider"] is None

    # Delete
    assert store.delete_agent(agent["agent_id"]) is True
    assert store.get_agent(agent["agent_id"]) is None


def test_session_and_message_run_lifecycle():
    agent = store.create_agent(
        name="Lifecycle Agent",
        system_prompt="Prompt",
    )

    # Create session
    session = store.create_session(agent["agent_id"], title="新しい会話")
    assert session["agent_id"] == agent["agent_id"]
    assert session["title"] == "新しい会話"

    # Start user run
    user_msg, run = store.start_user_run(session["session_id"], "明日の予定を教えて")
    assert user_msg["role"] == "user"
    assert user_msg["sequence"] == 1
    assert user_msg["content"] == "明日の予定を教えて"

    assert run["status"] == "running"
    assert run["user_message_id"] == user_msg["message_id"]
    assert run["assistant_message_id"] is None

    # Check session title was automatically updated from "新しい会話"
    updated_session = store.get_session(session["session_id"])
    assert updated_session["title"] == "明日の予定を教えて"

    # Complete run
    asst_msg, completed_run = store.complete_run(
        run["run_id"],
        assistant_content="明日の予定は10時からミーティングです。",
        used_tools=["calendar_read"],
        created_hitl_run_ids=["hrun_12345"],
    )
    assert asst_msg["role"] == "assistant"
    assert asst_msg["sequence"] == 2
    assert asst_msg["content"] == "明日の予定は10時からミーティングです。"

    assert completed_run["status"] == "succeeded"
    assert completed_run["assistant_message_id"] == asst_msg["message_id"]
    assert completed_run["used_tools"] == ["calendar_read"]
    assert completed_run["created_hitl_run_ids"] == ["hrun_12345"]

    # Verify messages and runs list
    messages = store.list_messages(session["session_id"])
    assert len(messages) == 2
    assert [m["role"] for m in messages] == ["user", "assistant"]

    runs = store.list_runs(session["session_id"])
    assert len(runs) == 1
    assert runs[0]["run_id"] == run["run_id"]


def test_fail_run():
    agent = store.create_agent(name="Fail Agent", system_prompt="Prompt")
    session = store.create_session(agent["agent_id"])
    _, run = store.start_user_run(session["session_id"], "エラーテスト")

    failed_run = store.fail_run(run["run_id"], "LLM call failed")
    assert failed_run["status"] == "failed"
    assert failed_run["error_message"] == "LLM call failed"


def test_cascade_deletions():
    agent = store.create_agent(name="Cascade Agent", system_prompt="Prompt")
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(session["session_id"], "テストメッセージ")
    store.complete_run(run["run_id"], "返答")

    conn = get_db_connection()

    # Verify records exist before delete
    assert store.get_session(session["session_id"]) is not None
    assert len(store.list_messages(session["session_id"])) == 2
    assert len(store.list_runs(session["session_id"])) == 1

    # Delete agent -> cascades to session, messages, runs
    store.delete_agent(agent["agent_id"])

    assert store.get_agent(agent["agent_id"]) is None
    assert store.get_session(session["session_id"]) is None

    cursor = conn.execute(
        "SELECT COUNT(*) FROM agent_messages WHERE session_id = ?;",
        (session["session_id"],),
    )
    assert cursor.fetchone()[0] == 0

    cursor = conn.execute(
        "SELECT COUNT(*) FROM agent_runs WHERE session_id = ?;",
        (session["session_id"],),
    )
    assert cursor.fetchone()[0] == 0
