"""Integration tests for ask_user conversational HITL across Agents and Coding Workspace."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from obsidian_ai_hub.agents import runtime as agent_runtime, store as agent_store
from obsidian_ai_hub.agents.ask_user_handler import handle_agent_ask_user, handle_coding_ask_user
from obsidian_ai_hub.coding import store as coding_store
from obsidian_ai_hub.hitl import service as hitl_service, store as hitl_store
from obsidian_ai_hub.hitl.dispatcher import HitlContext
from obsidian_ai_hub.runs.agent_worker import execute_agent_run
from obsidian_ai_hub.runs.coding_worker import execute_coding_run


def _configure_astream(mock_llm: MagicMock, turns: list[list[object]]) -> None:
    """Configure sequential async LLM turns yielding chunk lists."""
    remaining_turns = iter(turns)

    async def astream(_messages):
        turn = next(remaining_turns)
        for chunk in turn:
            yield chunk

    mock_llm.astream.side_effect = astream


@pytest.fixture
def agent_setup(tmp_path):
    """Create test agent and session."""
    agent = agent_store.create_agent(
        name="Test AskUser Agent",
        system_prompt="You are a helpful assistant.",
        tool_ids=["web_search", "ask_user"],
        provider="openai",
        model="gpt-4o",
    )
    session = agent_store.create_session(agent_id=agent["agent_id"])
    return agent, session


@pytest.fixture
def coding_setup(tmp_path):
    """Create test coding project and session."""
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)

    from obsidian_ai_hub.database import get_db_connection
    conn = get_db_connection()
    cur = conn.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status, project_path, created_at, updated_at)"
        " VALUES ('askuser-proj', 'AskUser Proj', 'personal', 'active', ?, datetime('now'), datetime('now'));",
        (str(repo),),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()

    session = coding_store.create_session(
        project_id=pid,
        backend="codex",
        repo_path=str(repo),
        title="AskUser Coding Session",
    )
    return session


@pytest.mark.anyio
async def test_agent_ask_user_interception_and_resumption(agent_setup):
    """Agent calls ask_user alone -> waiting_user + HITL run -> answer -> queued -> completed."""
    agent, session = agent_setup
    msg, run = agent_store.start_queued_run(session["session_id"], "詳細を尋ねてください")
    run_id = run["run_id"]

    # 1. First execution: LLM streams ask_user tool call
    ask_chunk = AIMessageChunk(
        content="質問があります。",
        tool_call_chunks=[
            {
                "name": "ask_user",
                "args": json.dumps({
                    "questions": [
                        {
                            "question_id": "q1",
                            "question": "どの範囲を対象にしますか？",
                            "choices": [
                                {"value": "frontend", "label": "フロントエンド"},
                                {"value": "backend", "label": "バックエンド"},
                            ],
                        }
                    ]
                }),
                "id": "call_ask_1",
                "index": 0,
            }
        ],
    )

    mock_llm = MagicMock()
    _configure_astream(mock_llm, [[ask_chunk]])
    mock_llm.bind_tools.return_value = mock_llm

    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm):
        await execute_agent_run(run_id)

    # Verify run transitioned to waiting_user and created a HITL run
    updated_run = agent_store.get_run(run_id)
    assert updated_run["status"] == "waiting_user"
    hitl_run_id = updated_run["hitl_run_id"]
    assert hitl_run_id is not None
    assert hitl_run_id.startswith("hitl_ask_")

    hitl_run = hitl_store.get_run(hitl_run_id)
    assert hitl_run is not None
    assert hitl_run["handler"] == "agents.ask_user"

    # Verify user_question SSE event was logged
    events = agent_store.list_run_events(run_id)
    event_types = [e["event_type"] for e in events]
    assert "user_question" in event_types

    # 2. User submits answer via submit_answer
    hitl_service.submit_answer(
        run_id=hitl_run_id,
        question_set_id="qset_1",
        question_key="q1",
        answer={"value": "frontend", "comment": None},
    )

    # 3. Dispatch/Handler executes handle_agent_ask_user
    ctx = HitlContext(
        run_id=hitl_run_id,
        checkpoint=hitl_run["checkpoint"],
        answers_by_question_key={"q1": "frontend"},
        conn=None,
        raw_answers_by_question_key={"q1": {"value": "frontend", "comment": None}},
    )
    handler_res = handle_agent_ask_user(ctx)
    assert handler_res.status == "completed"
    hitl_service.update_checkpoint(hitl_run_id, handler_res.checkpoint)

    # Verify run is back in queued status
    queued_run = agent_store.get_run(run_id)
    assert queued_run["status"] == "queued"
    assert queued_run["hitl_run_id"] == hitl_run_id

    # 4. Second execution: LLM receives answer and gives final response
    resumption_chunk = AIMessageChunk(content="フロントエンドの修正を開始します。")

    mock_llm_resumed = MagicMock()
    _configure_astream(mock_llm_resumed, [[resumption_chunk]])
    mock_llm_resumed.bind_tools.return_value = mock_llm_resumed

    captured_messages = []

    async def tracking_astream(messages):
        captured_messages.extend(messages)
        yield resumption_chunk

    mock_llm_resumed.astream.side_effect = tracking_astream

    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm_resumed):
        await execute_agent_run(run_id)

    # Verify run completed successfully
    final_run = agent_store.get_run(run_id)
    assert final_run["status"] == "succeeded"

    # Check that injected ToolMessage contained the structured answer
    tool_msgs = [m for m in captured_messages if isinstance(m, ToolMessage)]
    assert len(tool_msgs) >= 1
    assert "answers" in tool_msgs[0].content
    assert "frontend" in tool_msgs[0].content


@pytest.mark.anyio
async def test_coding_ask_user_interception_and_resumption(coding_setup):
    """Coding Workspace calls ask_user alone -> waiting_user -> answer -> queued -> completed."""
    session = coding_setup
    session_id = session["session_id"]
    _, run = coding_store.start_queued_run(session_id, "要件を確認してください")
    run_id = run["run_id"]

    # 1. First execution: Coding Orchestrator calls ask_user
    ask_ai_msg = MagicMock()
    ask_ai_msg.content = "仕様の確認です。"
    ask_ai_msg.tool_calls = [
        {
            "name": "ask_user",
            "args": {
                "questions": [
                    {
                        "question_id": "mode",
                        "question": "どのモードにしますか？",
                        "choices": [
                            {"value": "strict", "label": "厳格モード"},
                            {"value": "loose", "label": "緩格モード"},
                        ],
                    }
                ]
            },
            "id": "call_coding_ask_1",
        }
    ]

    def fake_create_llm(*args, **kwargs):
        mock_llm = MagicMock()
        mock_with = MagicMock()
        mock_with.ainvoke = AsyncMock(return_value=ask_ai_msg)
        mock_llm.bind_tools.return_value = mock_with
        return mock_llm

    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", side_effect=fake_create_llm):
        await execute_coding_run(run_id)

    updated_run = coding_store.get_run(run_id)
    assert updated_run["status"] == "waiting_user"
    hitl_run_id = updated_run["hitl_run_id"]
    assert hitl_run_id is not None

    events = coding_store.list_run_events(run_id)
    event_types = [e["event_type"] for e in events]
    assert "user_question" in event_types

    # 2. Submit answer via HITL
    hitl_service.submit_answer(
        run_id=hitl_run_id,
        question_set_id="qset_1",
        question_key="mode",
        answer={"value": "other", "comment": "カスタム設定"},
    )

    hitl_run = hitl_store.get_run(hitl_run_id)
    ctx = HitlContext(
        run_id=hitl_run_id,
        checkpoint=hitl_run["checkpoint"],
        answers_by_question_key={"mode": "other"},
        conn=None,
        raw_answers_by_question_key={"mode": {"value": "other", "comment": "カスタム設定"}},
    )
    handler_res = handle_coding_ask_user(ctx)
    assert handler_res.status == "completed"
    hitl_service.update_checkpoint(hitl_run_id, handler_res.checkpoint)

    queued_run = coding_store.get_run(run_id)
    assert queued_run["status"] == "queued"

    # 3. Second execution: Orchestrator resumes with answer ToolMessage and finishes
    final_ai_msg = MagicMock()
    final_ai_msg.content = "了解しました。カスタム設定で進行します。"
    final_ai_msg.tool_calls = []

    captured_messages = []

    def fake_create_llm_resumed(*args, **kwargs):
        mock_llm = MagicMock()
        mock_with = MagicMock()

        async def mock_ainvoke(messages):
            captured_messages.extend(messages)
            return final_ai_msg

        mock_with.ainvoke = mock_ainvoke
        mock_llm.bind_tools.return_value = mock_with
        return mock_llm

    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", side_effect=fake_create_llm_resumed):
        await execute_coding_run(run_id)

    final_run = coding_store.get_run(run_id)
    assert final_run["status"] == "completed"

    tool_msgs = [m for m in captured_messages if isinstance(m, ToolMessage)]
    assert len(tool_msgs) >= 1
    assert "other" in tool_msgs[0].content
    assert "カスタム設定" in tool_msgs[0].content


@pytest.mark.anyio
async def test_ask_user_mixed_tool_calls_returns_error(agent_setup):
    """Calling ask_user along with web_search in a single turn returns ToolMessage error."""
    agent, session = agent_setup
    _, run = agent_store.start_queued_run(session["session_id"], "混在テスト")
    run_id = run["run_id"]

    mixed_chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"name": "web_search", "args": '{"query":"python"}', "id": "call_web_1", "index": 0},
            {"name": "ask_user", "args": '{"questions":[{"question_id":"q1","question":"test","choices":[{"value":"a","label":"A"}]}]}', "id": "call_ask_1", "index": 1},
        ],
    )
    resumption_chunk = AIMessageChunk(content="単独で再試行します。")

    mock_llm = MagicMock()
    _configure_astream(mock_llm, [[mixed_chunk], [resumption_chunk]])
    mock_llm.bind_tools.return_value = mock_llm

    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm):
        await execute_agent_run(run_id)

    final_run = agent_store.get_run(run_id)
    assert final_run["status"] == "succeeded"


@pytest.mark.anyio
async def test_ask_user_cancellation_cancels_both_runs(agent_setup):
    """Cancelling a HITL run marks both HITL run and original run as cancelled without enqueuing."""
    agent, session = agent_setup
    _, run = agent_store.start_queued_run(session["session_id"], "質問してください")
    run_id = run["run_id"]

    ask_chunk = AIMessageChunk(
        content="質問です。",
        tool_call_chunks=[
            {
                "name": "ask_user",
                "args": '{"questions":[{"question_id":"q1","question":"キャンセルテスト","choices":[{"value":"a","label":"A"}]}]}',
                "id": "call_c1",
                "index": 0,
            }
        ],
    )

    mock_llm = MagicMock()
    _configure_astream(mock_llm, [[ask_chunk]])
    mock_llm.bind_tools.return_value = mock_llm

    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm):
        await execute_agent_run(run_id)

    waiting_run = agent_store.get_run(run_id)
    assert waiting_run["status"] == "waiting_user"
    hitl_run_id = waiting_run["hitl_run_id"]

    # Cancel HITL run via hitl_service
    hitl_service.cancel_run(hitl_run_id)

    # Verify both HITL run and Agent run are set to cancelled
    hitl_run = hitl_store.get_run(hitl_run_id)
    assert hitl_run["status"] == "cancelled"

    cancelled_agent_run = agent_store.get_run(run_id)
    assert cancelled_agent_run["status"] == "cancelled"
    # Cancel keeps hitl_run_id for audit/traceability of completed questions.
    assert cancelled_agent_run["hitl_run_id"] == hitl_run_id


def _ask_chunk(call_id, qid, qtext, choices):
    return AIMessageChunk(
        content="質問です。",
        tool_call_chunks=[
            {
                "name": "ask_user",
                "args": json.dumps({"questions": [{"question_id": qid, "question": qtext, "choices": choices}]}),
                "id": call_id,
                "index": 0,
            }
        ],
    )


@pytest.mark.anyio
async def test_agent_invalid_questions_bounce_without_hitl(agent_setup):
    """Reserved 'other', empty choices, and empty labels bounce as tool errors (no HITL)."""
    agent, session = agent_setup
    _, run = agent_store.start_queued_run(session["session_id"], "不正テスト")
    run_id = run["run_id"]

    invalid_sets = [
        [{"question_id": "q1", "question": "Q?", "choices": [{"value": "other", "label": "bad"}]}],
        [{"question_id": "q1", "question": "Q?", "choices": []}],
        [{"question_id": "q1", "question": "Q?", "choices": [{"value": "a", "label": ""}]}],
    ]
    turns = []
    for i, qs in enumerate(invalid_sets):
        turns.append([
            AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": "ask_user", "args": json.dumps({"questions": qs}), "id": f"bad_{i}", "index": 0}],
            )
        ])
    turns.append([AIMessageChunk(content="再試行で完了します。")])

    mock_llm = MagicMock()
    _configure_astream(mock_llm, turns)
    mock_llm.bind_tools.return_value = mock_llm

    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm):
        await execute_agent_run(run_id)

    final_run = agent_store.get_run(run_id)
    assert final_run["status"] == "succeeded"
    # No HITL run was created for invalid sets.
    assert final_run["hitl_run_id"] is None
    events = agent_store.list_run_events(run_id)
    assert "user_question" not in [e["event_type"] for e in events]


@pytest.mark.anyio
async def test_agent_second_question_accumulates_history(agent_setup):
    """Two ask_user rounds accumulate qa_history and inject both answers on resume."""
    from obsidian_ai_hub.agents.ask_user import build_resume_turns

    agent, session = agent_setup
    _, run = agent_store.start_queued_run(session["session_id"], "二度目の質問テスト")
    run_id = run["run_id"]
    choices = [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]

    mock_llm = MagicMock()
    _configure_astream(mock_llm, [[_ask_chunk("call_q1", "q1", "1問目?", choices)]])
    mock_llm.bind_tools.return_value = mock_llm
    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm):
        await execute_agent_run(run_id)
    hitl1 = agent_store.get_run(run_id)["hitl_run_id"]
    assert agent_store.get_run(run_id)["status"] == "waiting_user"

    hitl_service.submit_answer(run_id=hitl1, question_set_id="qset_1", question_key="q1", answer={"value": "a", "comment": None})
    cp1 = hitl_store.get_run(hitl1)["checkpoint"]
    ctx1 = HitlContext(run_id=hitl1, checkpoint=cp1, answers_by_question_key={"q1": "a"}, conn=None,
                       raw_answers_by_question_key={"q1": {"value": "a", "comment": None}})
    res1 = handle_agent_ask_user(ctx1)
    hitl_service.update_checkpoint(hitl1, res1.checkpoint)
    assert agent_store.get_run(run_id)["status"] == "queued"

    # Second interruption carries q1 history.
    mock_llm2 = MagicMock()
    _configure_astream(mock_llm2, [[_ask_chunk("call_q2", "q2", "2問目?", choices)]])
    mock_llm2.bind_tools.return_value = mock_llm2
    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm2):
        await execute_agent_run(run_id)
    run2 = agent_store.get_run(run_id)
    assert run2["status"] == "waiting_user"
    hitl2 = run2["hitl_run_id"]
    assert hitl2 != hitl1
    cp2 = json.loads(hitl_store.get_run(hitl2)["checkpoint"])
    assert len(cp2["qa_history"]) == 1
    assert cp2["qa_history"][0]["answers"] == {"q1": {"selection": "a", "text": None}}

    hitl_service.submit_answer(run_id=hitl2, question_set_id="qset_1", question_key="q2", answer={"value": "b", "comment": None})
    ctx2 = HitlContext(run_id=hitl2, checkpoint=hitl_store.get_run(hitl2)["checkpoint"],
                       answers_by_question_key={"q2": "b"}, conn=None,
                       raw_answers_by_question_key={"q2": {"value": "b", "comment": None}})
    res2 = handle_agent_ask_user(ctx2)
    hitl_service.update_checkpoint(hitl2, res2.checkpoint)
    merged = json.loads(res2.checkpoint)
    assert len(merged["qa_history"]) == 2
    assert len(build_resume_turns(merged)) == 2

    # Resume injects both Q&A turns in order.
    captured = []

    async def tracking_astream(messages):
        captured.extend(messages)
        yield AIMessageChunk(content="両回答を踏まえて完了します。")

    mock_llm3 = MagicMock()
    mock_llm3.astream.side_effect = tracking_astream
    mock_llm3.bind_tools.return_value = mock_llm3
    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm3):
        await execute_agent_run(run_id)
    assert agent_store.get_run(run_id)["status"] == "succeeded"
    tool_msgs = [m for m in captured if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 2
    assert "q1" in tool_msgs[0].content and "q2" in tool_msgs[1].content


def _coding_llm_factory(responses):
    """Build a create_llm side_effect yielding ainvoke responses in order."""
    remaining = list(responses)

    def fake_create_llm(*args, **kwargs):
        mock_llm = MagicMock()
        mock_with = MagicMock()

        async def mock_ainvoke(messages):
            return remaining.pop(0)

        mock_with.ainvoke = mock_ainvoke
        mock_llm.bind_tools.return_value = mock_with
        return mock_llm

    return fake_create_llm


@pytest.mark.anyio
async def test_coding_mixed_and_invalid_bounce_without_hitl(coding_setup):
    """Coding mixed ask_user and invalid choices bounce as errors without HITL."""
    session = coding_setup
    _, run = coding_store.start_queued_run(session["session_id"], "混在・不正テスト")
    run_id = run["run_id"]

    mixed = MagicMock()
    mixed.content = ""
    mixed.tool_calls = [
        {"name": "ask_user", "args": {"questions": [{"question_id": "q1", "question": "Q?", "choices": [{"value": "a", "label": "A"}]}]}, "id": "c_mix_ask"},
        {"name": "web_search", "args": {"query": "x"}, "id": "c_mix_web"},
    ]
    invalid = MagicMock()
    invalid.content = ""
    invalid.tool_calls = [
        {"name": "ask_user", "args": {"questions": [{"question_id": "q1", "question": "Q?", "choices": []}]}, "id": "c_bad"},
    ]
    final = MagicMock()
    final.content = "再試行で完了します。"
    final.tool_calls = []

    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm",
               side_effect=_coding_llm_factory([mixed, invalid, final])):
        await execute_coding_run(run_id)

    final_run = coding_store.get_run(run_id)
    assert final_run["status"] == "completed"
    assert final_run["hitl_run_id"] is None
    events = coding_store.list_run_events(run_id)
    assert "user_question" not in [e["event_type"] for e in events]


@pytest.mark.anyio
async def test_coding_cancel_keeps_hitl_link_and_sse_order(coding_setup):
    """Coding cancel keeps hitl_run_id; resume path emits user_question before done."""
    session = coding_setup
    _, run = coding_store.start_queued_run(session["session_id"], "取消・順序テスト")
    run_id = run["run_id"]

    ask = MagicMock()
    ask.content = "確認です。"
    ask.tool_calls = [
        {"name": "ask_user",
         "args": {"questions": [{"question_id": "mode", "question": "どのモード?", "choices": [{"value": "a", "label": "A"}]}]},
         "id": "c_cancel_1"},
    ]
    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", side_effect=_coding_llm_factory([ask])):
        await execute_coding_run(run_id)
    assert coding_store.get_run(run_id)["status"] == "waiting_user"
    hitl_id = coding_store.get_run(run_id)["hitl_run_id"]

    hitl_service.cancel_run(hitl_id)
    cancelled = coding_store.get_run(run_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["hitl_run_id"] == hitl_id

    # Separate run verifies SSE order: user_question persisted before done.
    _, run2 = coding_store.start_queued_run(session["session_id"], "順序テスト")
    run2_id = run2["run_id"]
    ask2 = MagicMock()
    ask2.content = "確認です。"
    ask2.tool_calls = [
        {"name": "ask_user",
         "args": {"questions": [{"question_id": "m", "question": "Q?", "choices": [{"value": "a", "label": "A"}]}]},
         "id": "c_ord_1"},
    ]
    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", side_effect=_coding_llm_factory([ask2])):
        await execute_coding_run(run2_id)
    hitl2 = coding_store.get_run(run2_id)["hitl_run_id"]
    hitl_service.submit_answer(run_id=hitl2, question_set_id="qset_1", question_key="m", answer={"value": "a", "comment": None})
    ctx = HitlContext(run_id=hitl2, checkpoint=hitl_store.get_run(hitl2)["checkpoint"],
                      answers_by_question_key={"m": "a"}, conn=None,
                      raw_answers_by_question_key={"m": {"value": "a", "comment": None}})
    res = handle_coding_ask_user(ctx)
    hitl_service.update_checkpoint(hitl2, res.checkpoint)
    assert coding_store.get_run(run2_id)["status"] == "queued"

    done_msg = MagicMock()
    done_msg.content = "完了します。"
    done_msg.tool_calls = []
    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", side_effect=_coding_llm_factory([done_msg])):
        await execute_coding_run(run2_id)
    assert coding_store.get_run(run2_id)["status"] == "completed"
    types = [e["event_type"] for e in coding_store.list_run_events(run2_id)]
    assert types.index("user_question") < types.index("done")
