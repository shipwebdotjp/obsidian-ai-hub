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


def test_migration_v24_adds_attachments_column():
    conn = get_db_connection()
    cursor = conn.execute("PRAGMA user_version;")
    version = cursor.fetchone()[0]
    assert version >= 24

    cursor = conn.execute("PRAGMA table_info(agent_messages);")
    columns = {row[1] for row in cursor.fetchall()}
    assert "attachments_json" in columns


def test_message_attachments_round_trip():
    agent = store.create_agent(name="Attachment Agent", system_prompt="Prompt")
    session = store.create_session(agent["agent_id"])

    attachments = [
        {
            "name": "photo.png",
            "mime_type": "image/png",
            "data": "iVBORw0KGgoAAAANSUhEUg==",
        },
        {
            "name": "scan.jpg",
            "mime_type": "image/jpeg",
            "data": "/9j/4AAQSkZJRgABAQ==",
        },
    ]
    user_msg, _ = store.start_user_run(
        session["session_id"], "この画像を見て", attachments=attachments
    )
    assert user_msg["attachments"] == attachments

    messages = store.list_messages(session["session_id"])
    assert len(messages) == 1
    assert messages[0]["attachments"] == attachments


def test_message_without_attachments_defaults_to_empty_list():
    agent = store.create_agent(name="No Attachment Agent", system_prompt="Prompt")
    session = store.create_session(agent["agent_id"])
    user_msg, _ = store.start_user_run(session["session_id"], "テキストだけ")
    assert user_msg["attachments"] == []


def test_image_only_message_uses_placeholder_title():
    agent = store.create_agent(name="Image-Only Agent", system_prompt="Prompt")
    session = store.create_session(agent["agent_id"])
    attachments = [{"name": "img.png", "mime_type": "image/png", "data": "AAAA"}]
    user_msg, _ = store.start_user_run(
        session["session_id"], "", attachments=attachments
    )
    assert user_msg["content"] == ""
    assert user_msg["attachments"] == attachments
    auto_titled = store.get_session(session["session_id"])
    assert auto_titled["title"] == "画像を送りました"


def test_truly_empty_message_is_rejected():
    agent = store.create_agent(name="Empty Empty Agent", system_prompt="Prompt")
    session = store.create_session(agent["agent_id"])
    with pytest.raises(ValueError, match="empty"):
        store.start_user_run(session["session_id"], "   ")


def test_update_session_title_and_edited_flag():
    agent = store.create_agent(name="Title Test Agent", system_prompt="Prompt")
    session = store.create_session(agent["agent_id"], title="新しい会話")

    assert session["title_is_edited"] is False

    # Auto title update (is_user_edit=False)
    auto_session = store.update_session_title(
        session["session_id"], "自動生成タイトル", is_user_edit=False
    )
    assert auto_session["title"] == "自動生成タイトル"
    assert auto_session["title_is_edited"] is False

    # User edit title (is_user_edit=True)
    user_session = store.update_session_title(
        session["session_id"], "ユーザー編集タイトル", is_user_edit=True
    )
    assert user_session["title"] == "ユーザー編集タイトル"
    assert user_session["title_is_edited"] is True

    # Overwriting attempt via auto title (is_user_edit=False) should be ignored
    ignored_session = store.update_session_title(
        session["session_id"], "自動上書きしようとするタイトル", is_user_edit=False
    )
    assert ignored_session["title"] == "ユーザー編集タイトル"
    assert ignored_session["title_is_edited"] is True

    # User edit via update_session
    updated = store.update_session(session["session_id"], title="PATCH編集タイトル")
    assert updated["title"] == "PATCH編集タイトル"
    assert updated["title_is_edited"] is True

    # Empty/whitespace title must be rejected (boundary condition)
    with pytest.raises(ValueError, match="empty"):
        store.update_session_title(session["session_id"], "   ")


def test_search_messages_across_agents_returns_message_results_and_literal_query():
    first_agent = store.create_agent(name="Search First", system_prompt="Prompt")
    second_agent = store.create_agent(name="Search Second", system_prompt="Prompt")
    first_session = store.create_session(first_agent["agent_id"], title="最初の会話")
    second_session = store.create_session(second_agent["agent_id"], title="次の会話")

    first_message, _ = store.start_user_run(
        first_session["session_id"], "横断検索で確認する進捗 100%_完了"
    )
    second_message, _ = store.start_user_run(
        second_session["session_id"], "別エージェントからも横断検索できます"
    )

    results = store.search_messages("横断検索")

    assert {item["message_id"] for item in results} == {
        first_message["message_id"],
        second_message["message_id"],
    }
    first_result = next(
        item for item in results if item["message_id"] == first_message["message_id"]
    )
    assert first_result["agent_id"] == first_agent["agent_id"]
    assert first_result["agent_name"] == "Search First"
    assert first_result["session_title"] == "最初の会話"
    assert "横断検索" in first_result["snippet"]

    literal_results = store.search_messages("%_")
    assert [item["message_id"] for item in literal_results] == [
        first_message["message_id"]
    ]

    with pytest.raises(ValueError, match="must not be empty"):
        store.search_messages("   ")


def test_agent_delegate_agent_ids_crud_and_deletion():
    child1 = store.create_agent(name="Child Agent 1", system_prompt="Prompt")
    child2 = store.create_agent(name="Child Agent 2", system_prompt="Prompt")

    # Parent agent with delegates
    parent = store.create_agent(
        name="Parent Agent",
        system_prompt="Parent prompt",
        delegate_agent_ids=[child1["agent_id"], child2["agent_id"]],
    )
    assert parent["delegate_agent_ids"] == [child1["agent_id"], child2["agent_id"]]

    # Non-existent delegation target is rejected
    with pytest.raises(ValueError, match="does not exist"):
        store.create_agent(
            name="Bad Target Agent",
            system_prompt="Prompt",
            delegate_agent_ids=["agent_fake12345"],
        )

    # Self delegation rejection
    with pytest.raises(ValueError, match="cannot set itself"):
        store.update_agent(
            parent["agent_id"],
            delegate_agent_ids=[parent["agent_id"]],
        )

    # Delete child1 -> child1 automatically removed from parent's delegate_agent_ids
    store.delete_agent(child1["agent_id"])
    updated_parent = store.get_agent(parent["agent_id"])
    assert updated_parent["delegate_agent_ids"] == [child2["agent_id"]]
