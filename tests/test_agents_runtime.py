import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from obsidian_ai_hub.agents import runtime, store
from obsidian_ai_hub.utils import execution_logger


def _configure_astream(mock_llm: MagicMock, turns: list[object]) -> None:
    """Configure sequential async LLM turns from chunk lists or exceptions."""
    remaining_turns = iter(turns)

    async def astream(_messages):
        turn = next(remaining_turns)
        if isinstance(turn, BaseException):
            raise turn
        for chunk in turn:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk

    mock_llm.astream.side_effect = astream


def _payloads(events: list[str]) -> list[dict]:
    return [json.loads(event.removeprefix("data: ").strip()) for event in events]


def test_validated_tool_calls_rejects_duplicate_provider_ids():
    message = AIMessage(
        content="",
        tool_calls=[
            {"name": "web_search", "args": {"query": "one"}, "id": "call_same"},
            {"name": "vault_search", "args": {"query": "two"}, "id": "call_same"},
        ],
    )

    with pytest.raises(ValueError, match="duplicate"):
        runtime._validated_tool_calls(
            message,
            {"web_search": object(), "vault_search": object()},
            iteration=1,
        )


@pytest.mark.anyio
async def test_agent_stream_sends_text_chunks_in_order_and_persists_exact_content():
    agent = store.create_agent(
        name="Stream Agent",
        system_prompt="Helpful assistant",
    )
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(session["session_id"], "こんにちは")

    mock_llm = MagicMock()
    _configure_astream(
        mock_llm,
        [
            [
                AIMessageChunk(content="こんにちは"),
                AIMessageChunk(
                    content="！お手伝いできますか？",
                    response_metadata={
                        "finish_reason": "stop",
                        "token_usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 20,
                            "total_tokens": 30,
                        },
                    },
                ),
            ]
        ],
    )
    mock_llm.bind_tools.return_value = mock_llm

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        events = [
            event
            async for event in runtime.generate_agent_stream(
                agent=agent,
                session=session,
                run=run,
                history_messages=[user_msg],
                user_content="こんにちは",
            )
        ]

    payloads = _payloads(events)
    text_events = [payload for payload in payloads if payload["type"] == "text"]
    done_payload = next(payload for payload in payloads if payload["type"] == "done")
    final_text = "".join(payload["delta"] for payload in text_events)

    assert [payload["type"] for payload in payloads] == [
        "thinking",
        "text",
        "text",
        "done",
    ]
    assert final_text == "こんにちは！お手伝いできますか？"
    assert done_payload["message"]["content"] == final_text
    assert done_payload["run"]["status"] == "succeeded"

    db_run = store.get_run(run["run_id"])
    assert db_run["status"] == "succeeded"
    persisted_message = store.get_message(done_payload["message"]["message_id"])
    assert persisted_message["content"] == final_text

    logs, total = execution_logger.list_execution_logs(kind="llm")
    assert total == 1
    log = execution_logger.get_llm_call_detail(logs[0]["id"])
    assert log["status"] == "succeeded"
    assert log["response"] == final_text
    assert log["prompt_tokens"] == 10
    assert log["completion_tokens"] == 20
    assert log["total_tokens"] == 30
    assert log["finish_reason"] == "stop"


@pytest.mark.anyio
async def test_agent_stream_detects_and_executes_a_completed_tool_call():
    agent = store.create_agent(
        name="Tool Agent",
        system_prompt="Schedule manager",
        tool_ids=["calendar_create_proposal"],
    )
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(
        session["session_id"], "8月25日10時に会議の予定を入れて"
    )

    mock_llm = MagicMock()
    _configure_astream(
        mock_llm,
        [
            [
                AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "calendar_create_proposal",
                            "args": '{"title":"会議","start_time":"2026-08-25T10:00:00+09:00"',
                            "id": "call_123",
                            "index": 0,
                        }
                    ],
                ),
                AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": None,
                            "args": "}",
                            "id": None,
                            "index": 0,
                        }
                    ],
                ),
            ],
            [
                AIMessageChunk(content="カレンダーへの"),
                AIMessageChunk(content="予定追加申請（HITL）を作成しました。"),
            ],
        ],
    )
    mock_llm.bind_tools.return_value = mock_llm

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        events = [
            event
            async for event in runtime.generate_agent_stream(
                agent=agent,
                session=session,
                run=run,
                history_messages=[user_msg],
                user_content="8月25日10時に会議の予定を入れて",
            )
        ]

    payloads = _payloads(events)
    detected = [
        payload for payload in payloads if payload["type"] == "tool_call_detected"
    ]
    starts = [payload for payload in payloads if payload["type"] == "tool_call_start"]
    ends = [payload for payload in payloads if payload["type"] == "tool_call_end"]
    done_payload = next(payload for payload in payloads if payload["type"] == "done")

    assert [payload["type"] for payload in payloads] == [
        "thinking",
        "tool_call_detected",
        "tool_call_start",
        "tool_call_end",
        "thinking",
        "text",
        "text",
        "done",
    ]
    assert detected == [
        {
            "type": "tool_call_detected",
            "call_key": "1:0",
            "tool_name": "calendar_create_proposal",
            "iteration": 1,
        }
    ]
    assert starts[0]["call_id"] == "call_123"
    assert starts[0]["call_key"] == detected[0]["call_key"]
    assert ends[0]["call_key"] == detected[0]["call_key"]
    assert ends[0]["status"] == "succeeded"
    assert (
        done_payload["message"]["content"]
        == "カレンダーへの予定追加申請（HITL）を作成しました。"
    )
    assert len(done_payload["hitl_run_ids"]) == 1
    assert done_payload["hitl_run_ids"][0].startswith("hrun_inbox_calendar_")

    db_run = store.get_run(run["run_id"])
    assert db_run["used_tools"] == ["calendar_create_proposal"]
    assert db_run["created_hitl_run_ids"] == done_payload["hitl_run_ids"]


@pytest.mark.anyio
async def test_agent_stream_validates_all_interleaved_tool_chunks_before_execution():
    agent = store.create_agent(
        name="Interleaved Tool Agent",
        system_prompt="Use tools",
        tool_ids=["web_search", "vault_search"],
    )
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(session["session_id"], "do both")

    stream_finished = False
    calls: list[tuple[str, dict]] = []

    def first_invoke(args):
        assert stream_finished
        calls.append(("web_search", args))
        return "first result"

    def second_invoke(args):
        assert stream_finished
        calls.append(("vault_search", args))
        return "second result"

    first_tool = SimpleNamespace(
        name="web_search", invoke=MagicMock(side_effect=first_invoke)
    )
    second_tool = SimpleNamespace(
        name="vault_search", invoke=MagicMock(side_effect=second_invoke)
    )

    mock_llm = MagicMock()

    async def astream(_messages):
        nonlocal stream_finished
        turn = mock_llm.astream.call_count
        if turn == 1:
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "web_search",
                        "args": '{"value":',
                        "id": None,
                        "index": 0,
                    }
                ],
            )
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "vault_search",
                        "args": '{"value":',
                        "id": "call_second",
                        "index": 1,
                    }
                ],
            )
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": None,
                        "args": "1}",
                        "id": None,
                        "index": 0,
                    }
                ],
            )
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": None,
                        "args": "2}",
                        "id": None,
                        "index": 1,
                    }
                ],
            )
            stream_finished = True
        else:
            yield AIMessageChunk(content="both complete")

    mock_llm.astream.side_effect = astream
    mock_llm.bind_tools.return_value = mock_llm

    with (
        patch(
            "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
        ),
        patch(
            "obsidian_ai_hub.agents.runtime.registry.resolve_tools_with_context",
            return_value=[first_tool, second_tool],
        ),
    ):
        events = [
            event
            async for event in runtime.generate_agent_stream(
                agent=agent,
                session=session,
                run=run,
                history_messages=[user_msg],
                user_content="do both",
            )
        ]

    payloads = _payloads(events)
    starts = [payload for payload in payloads if payload["type"] == "tool_call_start"]
    assert [payload["call_key"] for payload in starts] == ["1:0", "1:1"]
    assert starts[0]["call_id"] == "call_1_0"
    assert starts[1]["call_id"] == "call_second"
    assert calls == [("web_search", {"value": 1}), ("vault_search", {"value": 2})]
    assert payloads[-1]["type"] == "done"


@pytest.mark.anyio
async def test_agent_stream_rejects_invalid_tool_chunks_without_execution_or_hitl():
    agent = store.create_agent(
        name="Invalid Tool Agent",
        system_prompt="Use tools",
        tool_ids=["web_search"],
    )
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(session["session_id"], "unsafe")
    safe_tool = SimpleNamespace(
        name="web_search", invoke=MagicMock(return_value="should not run")
    )

    mock_llm = MagicMock()
    _configure_astream(
        mock_llm,
        [
            [
                AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "web_search",
                            "args": "{not valid json",
                            "id": "call_bad",
                            "index": 0,
                        }
                    ],
                )
            ]
        ],
    )
    mock_llm.bind_tools.return_value = mock_llm

    with (
        patch(
            "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
        ),
        patch(
            "obsidian_ai_hub.agents.runtime.registry.resolve_tools_with_context",
            return_value=[safe_tool],
        ),
    ):
        events = [
            event
            async for event in runtime.generate_agent_stream(
                agent=agent,
                session=session,
                run=run,
                history_messages=[user_msg],
                user_content="unsafe",
            )
        ]

    payloads = _payloads(events)
    safe_tool.invoke.assert_not_called()
    assert not [payload for payload in payloads if payload["type"] == "tool_call_start"]
    assert payloads[-1]["type"] == "error"
    db_run = store.get_run(run["run_id"])
    assert db_run["status"] == "failed"
    assert db_run["created_hitl_run_ids"] == []


@pytest.mark.anyio
async def test_agent_stream_error_handling_marks_run_and_llm_log_failed():
    agent = store.create_agent(
        name="Error Agent",
        system_prompt="Error tester",
    )
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(session["session_id"], "テスト")

    mock_llm = MagicMock()
    _configure_astream(mock_llm, [RuntimeError("API key invalid")])
    mock_llm.bind_tools.return_value = mock_llm

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        events = [
            event
            async for event in runtime.generate_agent_stream(
                agent=agent,
                session=session,
                run=run,
                history_messages=[user_msg],
                user_content="テスト",
            )
        ]

    payloads = _payloads(events)
    assert [payload["type"] for payload in payloads] == ["thinking", "error"]
    assert payloads[1]["run_id"] == run["run_id"]

    db_run = store.get_run(run["run_id"])
    assert db_run["status"] == "failed"
    assert "API key invalid" in db_run["error_message"]

    logs, total = execution_logger.list_execution_logs(kind="llm")
    assert total == 1
    log = execution_logger.get_llm_call_detail(logs[0]["id"])
    assert log["status"] == "failed"
    assert log["exception_type"] == "RuntimeError"
    assert "API key invalid" in log["exception_message"]


@pytest.mark.anyio
async def test_agent_stream_sends_image_blocks_for_current_and_history_messages():
    """Multimodal: attachments on the current turn AND on a prior user turn
    must both reach the LLM as image_url content blocks."""
    agent = store.create_agent(
        name="Vision Agent",
        system_prompt="Analyze images",
    )
    session = store.create_session(agent["agent_id"])

    prior_attachments = [
        {
            "name": "prior.png",
            "mime_type": "image/png",
            "data": "aGVsbG8K",
        }
    ]
    # Seed a prior user + assistant exchange that included an attachment on
    # the user turn, so we can verify the history HumanMessage is also rebuilt
    # as multimodal on the next turn.
    prior_msg, prior_run = store.start_user_run(
        session["session_id"],
        "前の画像",
        attachments=prior_attachments,
    )
    store.complete_run(
        prior_run["run_id"],
        assistant_content="これは前の画像ですね。",
    )

    captured_messages: list = []
    mock_llm = MagicMock()

    async def astream(messages):
        captured_messages.extend(messages)
        yield AIMessageChunk(content="今回と前の両方見ました")

    mock_llm.astream.side_effect = astream
    mock_llm.bind_tools.return_value = mock_llm

    current_attachments = [
        {
            "name": "current.png",
            "mime_type": "image/png",
            "data": "d29ybGQK",
        }
    ]

    history = store.list_messages(session["session_id"])
    user_msg, run = store.start_user_run(
        session["session_id"], "今の画像", attachments=current_attachments
    )

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        events = [
            event
            async for event in runtime.generate_agent_stream(
                agent=agent,
                session=session,
                run=run,
                history_messages=history,
                user_content="今の画像",
                attachments=current_attachments,
            )
        ]

    payloads = _payloads(events)
    assert payloads[-1]["type"] == "done"

    # SystemMessage + prior HumanMessage (with image) + prior AIMessage +
    # current HumanMessage (with image) = 4 messages
    langchain_user_messages = [
        m for m in captured_messages if m.__class__.__name__ == "HumanMessage"
    ]
    assert len(langchain_user_messages) == 2

    prior_blocked = langchain_user_messages[0].content
    current_blocked = langchain_user_messages[1].content

    assert isinstance(prior_blocked, list)
    assert any(
        block.get("type") == "image_url"
        and "data:image/png;base64,aGVsbG8K" in block["image_url"]["url"]
        for block in prior_blocked
    )

    assert isinstance(current_blocked, list)
    assert any(
        block.get("type") == "image_url"
        and "data:image/png;base64,d29ybGQK" in block["image_url"]["url"]
        for block in current_blocked
    )


@pytest.mark.anyio
async def test_agent_stream_drops_attachments_for_local_provider():
    """The 'local' provider has no vision support; attachments should be
    omitted from the HumanMessage and a warning logged, matching the existing
    llm_client behaviour."""
    agent = store.create_agent(
        name="Local Agent",
        system_prompt="Local provider",
        provider="local",
        model="",
    )
    session = store.create_session(agent["agent_id"])

    captured_messages: list = []
    mock_llm = MagicMock()

    async def astream(messages):
        captured_messages.extend(messages)
        yield AIMessageChunk(content="ローカル応答")

    mock_llm.astream.side_effect = astream
    mock_llm.bind_tools.return_value = mock_llm

    attachments = [
        {"name": "img.png", "mime_type": "image/png", "data": "Zm9v"}
    ]
    user_msg, run = store.start_user_run(
        session["session_id"], "テキスト質問", attachments=attachments
    )

    # We patch create_langchain_llm so the local branch is bypassed, but the
    # runtime's _build_user_message still consults agent["provider"] for the
    # multimodal decision.
    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        events = [
            event
            async for event in runtime.generate_agent_stream(
                agent=agent,
                session=session,
                run=run,
                history_messages=[user_msg],
                user_content="テキスト質問",
                attachments=attachments,
            )
        ]

    assert _payloads(events)[-1]["type"] == "done"

    user_message = next(
        m for m in captured_messages if m.__class__.__name__ == "HumanMessage"
    )
    assert isinstance(user_message.content, str)
    assert user_message.content == "テキスト質問"


def test_generate_session_title_truncates_and_cleans():
    with patch(
        "obsidian_ai_hub.agents.runtime.generate_llm_response",
        return_value='  "Pythonの基本学習について"  ',
    ):
        title = runtime.generate_session_title("Pythonを学びたい", "Pythonの基礎から学びましょう")
        assert title == "Pythonの基本学習について"


@pytest.mark.anyio
async def test_agent_stream_generates_title_only_on_initial_turn():
    agent = store.create_agent(
        name="Title Generation Agent",
        system_prompt="Helpful assistant",
    )
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(session["session_id"], "最初の質問")

    mock_llm = MagicMock()
    _configure_astream(
        mock_llm,
        [[AIMessageChunk(content="最初の回答")]],
    )
    mock_llm.bind_tools.return_value = mock_llm

    with (
        patch(
            "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
        ),
        patch(
            "obsidian_ai_hub.agents.runtime.generate_session_title",
            return_value="自動生成会話タイトル",
        ) as mock_gen_title,
    ):
        # 1st Turn
        events = [
            event
            async for event in runtime.generate_agent_stream(
                agent=agent,
                session=session,
                run=run,
                history_messages=[user_msg],
                user_content="最初の質問",
            )
        ]
        assert mock_gen_title.call_count == 1
        kwargs = mock_gen_title.call_args.kwargs
        assert kwargs["user_content"] == "最初の質問"
        assert kwargs.get("assistant_content") == "最初の回答"
        updated_session = store.get_session(session["session_id"])
        assert updated_session["title"] == "自動生成会話タイトル"

        # 2nd Turn
        mock_gen_title.reset_mock()
        user_msg_2, run_2 = store.start_user_run(session["session_id"], "2回目の質問")
        history = store.list_messages(session["session_id"])
        _configure_astream(
            mock_llm,
            [[AIMessageChunk(content="2回目の回答")]],
        )

        events_2 = [
            event
            async for event in runtime.generate_agent_stream(
                agent=agent,
                session=session,
                run=run_2,
                history_messages=history,
                user_content="2回目の質問",
            )
        ]
        # Title generation should NOT be called on 2nd turn
        assert mock_gen_title.call_count == 0
        final_session = store.get_session(session["session_id"])
        assert final_session["title"] == "自動生成会話タイトル"
