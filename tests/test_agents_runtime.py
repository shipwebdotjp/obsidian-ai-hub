import json
from unittest.mock import MagicMock, patch
import pytest
from langchain_core.messages import AIMessage

from obsidian_ai_hub.agents import registry, runtime, store


@pytest.mark.anyio
async def test_agent_stream_simple_response():
    agent = store.create_agent(
        name="Stream Agent",
        system_prompt="Helpful assistant",
    )
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(session["session_id"], "こんにちは")

    mock_llm = MagicMock()
    mock_ai_msg = AIMessage(content="こんにちは！お手伝いできることはありますか？")
    mock_llm.invoke.return_value = mock_ai_msg
    mock_llm.bind_tools.return_value = mock_llm

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        events = []
        async for event in runtime.generate_agent_stream(
            agent=agent,
            session=session,
            run=run,
            history_messages=[user_msg],
            user_content="こんにちは",
        ):
            events.append(event)

    assert len(events) == 2

    # Parse text event
    text_payload = json.loads(events[0].replace("data: ", "").strip())
    assert text_payload["type"] == "text"
    assert "こんにちは" in text_payload["delta"]

    # Parse done event
    done_payload = json.loads(events[1].replace("data: ", "").strip())
    assert done_payload["type"] == "done"
    assert done_payload["message"]["role"] == "assistant"
    assert done_payload["run"]["status"] == "succeeded"

    # Verify DB
    db_run = store.get_run(run["run_id"])
    assert db_run["status"] == "succeeded"
    assert db_run["assistant_message_id"] == done_payload["message"]["message_id"]


@pytest.mark.anyio
async def test_agent_stream_with_tool_call():
    agent = store.create_agent(
        name="Tool Agent",
        system_prompt="Schedule manager",
        tool_ids=["calendar_create_proposal"],
    )
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(
        session["session_id"], "8月25日10時に会議の予定を入れて"
    )

    # First invoke returns tool_call
    ai_tool_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "calendar_create_proposal",
                "args": {
                    "title": "会議",
                    "start_time": "2026-08-25T10:00:00+09:00",
                },
                "id": "call_123",
            }
        ],
    )
    # Second invoke returns final answer text
    ai_final_msg = AIMessage(
        content="カレンダーへの予定追加申請（HITL）を作成しました。"
    )

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [ai_tool_msg, ai_final_msg]
    mock_llm.bind_tools.return_value = mock_llm

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        events = []
        async for event in runtime.generate_agent_stream(
            agent=agent,
            session=session,
            run=run,
            history_messages=[user_msg],
            user_content="8月25日10時に会議の予定を入れて",
        ):
            events.append(event)

    done_payload = json.loads(events[-1].replace("data: ", "").strip())
    assert done_payload["type"] == "done"
    assert len(done_payload["hitl_run_ids"]) == 1
    assert done_payload["hitl_run_ids"][0].startswith("hrun_inbox_calendar_")

    db_run = store.get_run(run["run_id"])
    assert db_run["used_tools"] == ["calendar_create_proposal"]
    assert db_run["created_hitl_run_ids"] == done_payload["hitl_run_ids"]


@pytest.mark.anyio
async def test_agent_stream_error_handling():
    agent = store.create_agent(
        name="Error Agent",
        system_prompt="Error tester",
    )
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(session["session_id"], "テスト")

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API key invalid")
    mock_llm.bind_tools.return_value = mock_llm

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        events = []
        async for event in runtime.generate_agent_stream(
            agent=agent,
            session=session,
            run=run,
            history_messages=[user_msg],
            user_content="テスト",
        ):
            events.append(event)

    assert len(events) == 1
    error_payload = json.loads(events[0].replace("data: ", "").strip())
    assert error_payload["type"] == "error"
    assert error_payload["error"] == "AIエージェントの実行中にエラーが発生しました。"
    assert error_payload["run_id"] == run["run_id"]

    db_run = store.get_run(run["run_id"])
    assert db_run["status"] == "failed"
    assert "API key invalid" in db_run["error_message"]
