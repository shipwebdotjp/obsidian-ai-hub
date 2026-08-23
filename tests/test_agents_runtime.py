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

    payloads = [json.loads(e.removeprefix("data: ").strip()) for e in events]
    thinking = [p for p in payloads if p["type"] == "thinking"]
    text_events = [p for p in payloads if p["type"] == "text"]
    done_events = [p for p in payloads if p["type"] == "done"]

    assert len(thinking) == 1
    assert thinking[0]["iteration"] == 1
    assert len(text_events) == 1
    assert "こんにちは" in text_events[0]["delta"]
    assert len(done_events) == 1

    done_payload = done_events[0]
    assert done_payload["message"]["role"] == "assistant"
    assert done_payload["run"]["status"] == "succeeded"

    # Verify ordering: thinking -> text -> done
    assert payloads[0]["type"] == "thinking"
    assert payloads[1]["type"] == "text"
    assert payloads[2]["type"] == "done"

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

    payloads = [json.loads(e.removeprefix("data: ").strip()) for e in events]
    done_payload = next(p for p in payloads if p["type"] == "done")
    assert len(done_payload["hitl_run_ids"]) == 1
    assert done_payload["hitl_run_ids"][0].startswith("hrun_inbox_calendar_")

    # Verify streaming progress events
    thinking = [p for p in payloads if p["type"] == "thinking"]
    starts = [p for p in payloads if p["type"] == "tool_call_start"]
    ends = [p for p in payloads if p["type"] == "tool_call_end"]
    # Two thinking events (iteration 1 before tool call, iteration 2 before final answer)
    assert len(thinking) == 2
    assert thinking[0]["iteration"] == 1
    assert thinking[1]["iteration"] == 2
    assert len(starts) == 1
    assert starts[0]["tool_name"] == "calendar_create_proposal"
    assert starts[0]["call_id"] == "call_123"
    assert len(ends) == 1
    assert ends[0]["tool_name"] == "calendar_create_proposal"
    assert ends[0]["status"] == "succeeded"
    assert ends[0]["call_id"] == "call_123"
    # Ordering: thinking(1) -> start -> end -> thinking(2) -> text -> done
    types = [p["type"] for p in payloads]
    assert types == ["thinking", "tool_call_start", "tool_call_end", "thinking", "text", "done"]

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

    payloads = [json.loads(e.removeprefix("data: ").strip()) for e in events]
    # thinking is emitted before the failing invoke, then error
    assert len(payloads) == 2
    assert payloads[0]["type"] == "thinking"
    assert payloads[0]["iteration"] == 1
    assert payloads[1]["type"] == "error"
    error_payload = payloads[1]
    assert error_payload["error"] == "AIエージェントの実行中にエラーが発生しました。"
    assert error_payload["run_id"] == run["run_id"]

    db_run = store.get_run(run["run_id"])
    assert db_run["status"] == "failed"
    assert "API key invalid" in db_run["error_message"]
