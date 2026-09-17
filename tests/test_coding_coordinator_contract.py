"""Tests for the Coordinator/CLI-Worker control contract.

Covers: exclusive <cli_request>/<final_report> parsing (valid, empty,
duplicate, mixed, missing), self-correction resend semantics, history role
injection (cli_request as assistant), Worker output passthrough (ACP
elicitation carries follow-up input), and single-shot --coding waiting_user
output.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from obsidian_ai_hub.coding.orchestrator import (
    CodingOrchestrator,
    parse_coordinator_response,
)


def test_parse_valid_continue():
    raw = "進捗メモ\n<cli_request>\n元依頼と停止契約\n</cli_request>"
    res = parse_coordinator_response(raw)
    assert res.kind == "continue"
    assert res.cli_prompt == "元依頼と停止契約"
    assert "<cli_request>" not in res.clean_text
    assert "進捗メモ" in res.clean_text


def test_parse_valid_complete():
    raw = "前置き\n<final_report>\nテスト2件成功、file.pyを変更\n</final_report>\n後置き"
    res = parse_coordinator_response(raw)
    assert res.kind == "complete"
    assert res.final_report == "テスト2件成功、file.pyを変更"
    assert res.clean_text == "テスト2件成功、file.pyを変更"
    assert "<final_report>" not in res.clean_text


def test_parse_empty_is_invalid():
    assert parse_coordinator_response("<cli_request>   </cli_request>").violation == "empty"
    assert parse_coordinator_response("<final_report>\n\n</final_report>").violation == "empty"


def test_parse_duplicate_mixed_missing_are_invalid():
    dup = "<cli_request>a</cli_request>\n<cli_request>b</cli_request>"
    assert parse_coordinator_response(dup).violation == "duplicate"
    dup_final = "<final_report>a</final_report><final_report>b</final_report>"
    assert parse_coordinator_response(dup_final).violation == "duplicate"
    mixed = "<cli_request>a</cli_request>\n<final_report>b</final_report>"
    assert parse_coordinator_response(mixed).violation == "mixed"
    assert parse_coordinator_response("タグなしの完了報告").violation == "missing"


def test_parse_retry_success_after_violation():
    first = parse_coordinator_response("タグなし報告")
    assert first.kind == "invalid"
    second = parse_coordinator_response("<final_report>根拠つき最終報告</final_report>")
    assert second.kind == "complete"
    # Two consecutive violations stay invalid (caller must fail the run).
    third = parse_coordinator_response("まだタグなし")
    assert third.kind == "invalid"


def test_history_injects_cli_request_as_assistant_and_worker_as_observation():
    orch = CodingOrchestrator(tool_ids=[])
    history = [
        {"role": "user", "content": "バグを直して"},
        {"role": "cli_request", "content": "元依頼と停止契約"},
        {"role": "worker", "content": "調査結果です"},
    ]
    msgs = orch._build_messages(history, "/repo", "opencode")
    assert isinstance(msgs[1], HumanMessage)
    assert isinstance(msgs[2], AIMessage)
    assert "自身の過去の判断" in str(msgs[2].content)
    assert isinstance(msgs[3], HumanMessage)
    assert "観測情報" in str(msgs[3].content)


@pytest.mark.anyio
async def test_coding_orchestrator_never_binds_agent_delegate():
    """The coding Coordinator has no parent agent run, so even an explicit or
    legacy tool_ids request must not bind agent_delegate to its LLM."""
    captured: dict = {}
    mock_with = MagicMock()

    def bind_tools(tools):
        captured["tools"] = tools
        return mock_with

    mock_llm = MagicMock()
    mock_llm.bind_tools.side_effect = bind_tools

    async def ainvoke(_messages):
        return AIMessage(content="<final_report>完了報告</final_report>")

    mock_with.ainvoke = ainvoke

    orch = CodingOrchestrator(tool_ids=["agent_delegate", "ask_user"])
    with patch(
        "obsidian_ai_hub.coding.orchestrator.create_langchain_llm",
        return_value=mock_llm,
    ):
        events = [
            event
            async for event in orch.generate_response_events(
                history=[{"role": "user", "content": "修正して"}],
                repo_path="/repo",
                backend_name="codex",
            )
        ]

    bound_names = [t.name for t in captured["tools"]]
    assert "agent_delegate" not in bound_names
    assert "ask_user" in bound_names
    assert any(event.get("type") == "text" for event in events)


@pytest.fixture
def coding_session_setup(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "README.md").write_text("# R\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)

    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    cur = conn.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status, project_path, created_at, updated_at)"
        " VALUES ('coord-proj', 'Coord', 'personal', 'active', ?, datetime('now'), datetime('now'));",
        (str(repo),),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()

    from obsidian_ai_hub.coding import store as coding_store

    session = coding_store.create_session(
        project_id=pid, backend="opencode", repo_path=str(repo), title="Coord Session"
    )
    return session


def _coding_llm_factory(responses):
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
async def test_worker_output_leads_to_waiting_user(coding_session_setup):
    """Worker output -> Coordinator ask_user -> waiting_user + user_question."""
    from obsidian_ai_hub.coding import acp as acp_module
    from obsidian_ai_hub.coding import store as coding_store
    from obsidian_ai_hub.runs.coding_worker import execute_coding_run

    session_id = coding_session_setup["session_id"]
    _, run = coding_store.start_queued_run(session_id, "仕様を実装して")
    run_id = run["run_id"]

    first = MagicMock()
    first.content = "調査します。\n<cli_request>\n元依頼・制約・受入条件。\n</cli_request>"
    first.tool_calls = []
    ask = MagicMock()
    ask.content = "判断が必要です。"
    ask.tool_calls = [
        {
            "name": "ask_user",
            "args": {
                "questions": [
                    {
                        "question_id": "mode",
                        "question": "どのモードにしますか？",
                        "choices": [
                            {"value": "a", "label": "A"},
                            {"value": "b", "label": "B"},
                        ],
                    }
                ]
            },
            "id": "call_coord_ask_1",
        }
    ]

    worker_res = acp_module.AcpExecutionResult(
        acp_session_id="acp_block1",
        output="調査済み。判断Xが必要。",
        exit_code=0,
    )

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.create_langchain_llm",
            side_effect=_coding_llm_factory([first, ask]),
        ),
        patch(
            "obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn",
            return_value=worker_res,
        ),
    ):
        await execute_coding_run(run_id)

    updated = coding_store.get_run(run_id)
    assert updated["status"] == "waiting_user"
    assert updated["hitl_run_id"] is not None
    events = coding_store.list_run_events(run_id)
    assert "user_question" in [e["event_type"] for e in events]

    messages = coding_store.list_messages(session_id)
    worker_msgs = [m for m in messages if m["role"] == "worker"]
    assert worker_msgs
    assert "調査済み" in worker_msgs[-1]["content"]


@pytest.mark.anyio
async def test_protocol_double_violation_fails_run(coding_session_setup):
    """Tag-less responses twice -> explicit failed (never silent completed)."""
    from obsidian_ai_hub.coding import store as coding_store
    from obsidian_ai_hub.runs.coding_worker import execute_coding_run

    session_id = coding_session_setup["session_id"]
    _, run = coding_store.start_queued_run(session_id, "壊れた応答の検証")
    run_id = run["run_id"]

    bad1 = MagicMock()
    bad1.content = "タグなし報告1"
    bad1.tool_calls = []
    bad2 = MagicMock()
    bad2.content = "タグなし報告2"
    bad2.tool_calls = []

    with patch(
        "obsidian_ai_hub.coding.orchestrator.create_langchain_llm",
        side_effect=_coding_llm_factory([bad1, bad2]),
    ):
        await execute_coding_run(run_id)

    failed = coding_store.get_run(run_id)
    assert failed["status"] == "failed"
    assert "protocol" in (failed.get("error_message") or "").lower()


@pytest.mark.anyio
async def test_collect_coding_result_waiting_user_success():
    """Single-shot collector treats user_question as ok waiting_user."""
    from obsidian_ai_hub.coding import cli as coding_cli
    from obsidian_ai_hub.coding import store as coding_store

    async def _waiting_stream(session_id, prompt):
        yield f"data: {json.dumps({'event': 'start', 'run_id': 'crun_wait1', 'is_dirty': False, 'dirty_summary': None}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'event': 'user_question', 'hitl_run_id': 'hitl_ask_w1', 'question_set_id': 'qset_1', 'questions': [{'question_id': 'q1', 'question': 'Q?', 'choices': []}]}, ensure_ascii=False)}\n\n"

    with (
        patch.object(
            coding_cli.service, "run_coding_turn_stream", side_effect=_waiting_stream
        ),
        patch.object(
            coding_cli.store,
            "get_session",
            return_value={"session_id": "cses_w1", "project_id": 1, "title": "T"},
        ),
        patch.object(
            coding_cli.store,
            "get_run",
            return_value={"run_id": "crun_wait1", "status": "waiting_user", "hitl_run_id": "hitl_ask_w1"},
        ),
    ):
        result = await coding_cli._collect_coding_result("cses_w1", "prompt", True)

    assert result["ok"] is True
    assert result["run"]["status"] == "waiting_user"
    assert result["waiting_for_user"]["hitl_run_id"] == "hitl_ask_w1"
    assert result["waiting_for_user"]["questions"][0]["question_id"] == "q1"
    # Existing failure/cancel contract is untouched.
    assert coding_store.is_coding_terminal("completed") is True
    assert coding_store.is_coding_terminal("waiting_user") is False


def test_cli_json_waiting_output_contract(capsys):
    """--coding JSON in waiting_user returns ok:true with waiting_for_user."""
    from obsidian_ai_hub.coding import cli as coding_cli

    fake_result = {
        "ok": True,
        "response_text": "",
        "session": {"session_id": "cses_w2", "project_id": 7, "title": "T"},
        "run": {"run_id": "crun_w2", "status": "waiting_user", "hitl_run_id": "hitl_ask_w2"},
        "run_id": "crun_w2",
        "git_status": {"branch": "main", "ahead": 0, "behind": 0, "insertions": 0, "deletions": 0},
        "done_data": None,
        "error_message": None,
        "error_type": None,
        "worker_done": None,
        "waiting_for_user": {
            "hitl_run_id": "hitl_ask_w2",
            "question_set_id": "qset_1",
            "questions": [{"question_id": "q1", "question": "Q?"}],
        },
    }

    async def _fake_collect(session_id, prompt, json_output):
        return fake_result

    with (
        patch.object(coding_cli, "_collect_coding_result", side_effect=_fake_collect),
        patch.object(
            coding_cli, "_get_resume_session",
            return_value={"session_id": "cses_w2", "project_id": 7, "title": "T"},
        ),
    ):
        try:
            coding_cli.main_coding(
                project_id=None, resume_session="cses_w2", prompt="hi", json_output=True
            )
        except SystemExit as exc:
            pytest.fail(f"waiting_user must exit 0, got {exc.code}")

    out = json.loads(capsys.readouterr().out.strip())
    assert out["ok"] is True
    assert out["run"]["status"] == "waiting_user"
    assert out["waiting_for_user"]["hitl_run_id"] == "hitl_ask_w2"
