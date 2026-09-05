"""Carry-over of past orchestrator tool results into the Coding orchestrator."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from obsidian_ai_hub.coding import store as coding_store
from obsidian_ai_hub.coding.orchestrator import (
    CodingOrchestrator,
    _build_prior_tool_results_block,
    _format_prior_run,
    _format_prior_tool_call,
    _load_prior_tool_context,
)


@pytest.fixture
def coding_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
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
        " VALUES ('carry-proj', 'Carry Proj', 'personal', 'active', ?, datetime('now'), datetime('now'));",
        (str(repo),),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    sess = coding_store.create_session(
        project_id=pid, backend="opencode", repo_path=str(repo), title="Carry"
    )
    return sess, str(repo)


def _complete_run_with_calls(session_id, content, calls):
    _, run = coding_store.start_queued_run(session_id, content)
    run_id = run["run_id"]
    coding_store.transition_run_status(run_id, "running")
    for i, c in enumerate(calls):
        call_id = c.get("call_id", f"cotc_{run_id[-4:]}_{i}")
        coding_store.create_orchestrator_tool_call(
            call_id=call_id,
            run_id=run_id,
            phase="initial",
            phase_turn=1,
            iteration=1,
            call_index=i,
            call_key=f"1:1:{i}",
            tool_name=c["tool_name"],
            args=c.get("args", {}),
            status="running",
        )
        coding_store.update_orchestrator_tool_call(
            call_id=call_id,
            status=c.get("status", "succeeded"),
            result=c.get("result", ""),
            error=c.get("error"),
        )
    coding_store.transition_run_status(run_id, "completed", finished=True)
    return run_id


def _capture_llm():
    """Return (mock_llm, bound, captured) with a no-tool final response."""
    captured = []
    final = MagicMock()
    final.tool_calls = None
    final.content = "done"

    async def _ainvoke(messages):
        captured.extend(messages)
        return final

    bound = MagicMock()
    bound.ainvoke = _ainvoke
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = bound
    # allowed_tools may be empty (tool_ids=[]) so the orchestrator awaits
    # llm.ainvoke directly instead of the bound object.
    mock_llm.ainvoke = _ainvoke
    return mock_llm, bound, captured


def _system_content(captured):
    sys_msgs = [m for m in captured if m.__class__.__name__ == "SystemMessage"]
    assert sys_msgs, "SystemMessage must be sent to the LLM"
    return sys_msgs[0].content


@pytest.mark.anyio
async def test_small_result_injected_and_current_utterance_not_duplicated(coding_session):
    sess, repo = coding_session
    sid = sess["session_id"]
    _complete_run_with_calls(
        sid,
        "first",
        [{"tool_name": "web_search", "args": {"q": "cats"}, "result": "SMALL_RESULT_CODING_ABC"}],
    )

    orch = CodingOrchestrator(tool_ids=[])
    mock_llm, _, captured = _capture_llm()
    with (
        patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", return_value=mock_llm),
        patch("obsidian_ai_hub.agents.registry.resolve_tools_with_context", return_value=[]),
    ):
        async for _ in orch.generate_response_events(
            history=[{"role": "user", "content": "CURRENT_UTTERANCE_CODING_XYZ"}],
            repo_path=repo,
            backend_name="opencode",
            session_id=sid,
            current_run_id="crun_current_none",
        ):
            pass
    sys_content = _system_content(captured)
    assert "SMALL_RESULT_CODING_ABC" in sys_content
    assert "<untrusted_prior_tool_results>" in sys_content
    block = sys_content.split("<untrusted_prior_tool_results>")[1].split("</untrusted_prior_tool_results>")[0]
    assert "CURRENT_UTTERANCE_CODING_XYZ" not in block


@pytest.mark.anyio
async def test_only_last_three_completed_runs_carried(coding_session):
    sess, repo = coding_session
    sid = sess["session_id"]
    for i in range(4):
        _complete_run_with_calls(
            sid, f"q{i}", [{"tool_name": "web_search", "result": f"CODING_MARKER_{i}"}]
        )
    # non-completed run with tool calls must be ignored
    _, running = coding_store.start_queued_run(sid, "running q")
    coding_store.transition_run_status(running["run_id"], "running")
    coding_store.create_orchestrator_tool_call(
        call_id="cotc_running_1",
        run_id=running["run_id"],
        phase="initial",
        phase_turn=1,
        iteration=1,
        call_index=0,
        call_key="1:1:0",
        tool_name="web_search",
        args={},
        status="running",
    )
    coding_store.update_orchestrator_tool_call(
        call_id="cotc_running_1", status="succeeded", result="RUNNING_MARKER"
    )

    orch = CodingOrchestrator(tool_ids=[])
    mock_llm, _, captured = _capture_llm()
    with (
        patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", return_value=mock_llm),
        patch("obsidian_ai_hub.agents.registry.resolve_tools_with_context", return_value=[]),
    ):
        async for _ in orch.generate_response_events(
            history=[{"role": "user", "content": "target"}],
            repo_path=repo,
            backend_name="opencode",
            session_id=sid,
            current_run_id="crun_target",
        ):
            pass
    block = _system_content(captured).split("<untrusted_prior_tool_results>")[1].split("</untrusted_prior_tool_results>")[0]
    assert "CODING_MARKER_0" not in block
    assert "CODING_MARKER_1" in block
    assert "CODING_MARKER_2" in block
    assert "CODING_MARKER_3" in block
    assert "RUNNING_MARKER" not in block


def test_excerpt_budget_and_omission():
    long_result = "X" * 2000
    txt = _format_prior_tool_call(
        {"call_id": "c1", "tool_name": "web_search", "args": {"q": "hi"}, "result": long_result, "status": "succeeded", "error": None}
    )
    assert long_result[:1000] in txt
    assert "first 1000" in txt

    many = [
        {"call_id": f"c{i}", "tool_name": "web_search", "args": {"q": f"q-{i}-" + "Y" * 400}, "result": "R" * 1200, "status": "succeeded", "error": None}
        for i in range(10)
    ]
    run_txt = _format_prior_run("crun_test", many, 4000)
    assert len(run_txt) <= 4000
    assert "omitted" in run_txt


@pytest.mark.anyio
async def test_safety_block_always_present(coding_session):
    sess, repo = coding_session
    orch = CodingOrchestrator(tool_ids=[])
    mock_llm, _, captured = _capture_llm()
    with (
        patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", return_value=mock_llm),
        patch("obsidian_ai_hub.agents.registry.resolve_tools_with_context", return_value=[]),
    ):
        async for _ in orch.generate_response_events(
            history=[{"role": "user", "content": "hello"}],
            repo_path=repo,
            backend_name="opencode",
            session_id=sess["session_id"],
            current_run_id="crun_none",
        ):
            pass
    content = _system_content(captured)
    assert "<untrusted_prior_tool_results>" in content
    assert "untrusted" in content.lower() or "参考情報" in content
    assert ("再実行" in content or "再取得" in content or "re-run" in content.lower())


@pytest.mark.anyio
async def test_hitl_resume_includes_preinterruption_calls_and_qa(coding_session):
    from obsidian_ai_hub.hitl import service as hitl_service
    from obsidian_ai_hub.hitl import store as hitl_store

    sess, repo = coding_session
    sid = sess["session_id"]
    _, run = coding_store.start_queued_run(sid, "need ask")
    run_id = run["run_id"]
    coding_store.transition_run_status(run_id, "running")
    coding_store.create_orchestrator_tool_call(
        call_id="cotc_pre_1",
        run_id=run_id,
        phase="initial",
        phase_turn=1,
        iteration=1,
        call_index=0,
        call_key="1:1:0",
        tool_name="web_search",
        args={"q": "pre"},
        status="running",
    )
    coding_store.update_orchestrator_tool_call(
        call_id="cotc_pre_1", status="succeeded", result="PRETOOL_CODING_777"
    )

    ask_args = {"questions": [{"question_id": "q1", "question": "which?", "choices": [{"value": "a", "label": "A"}]}]}
    checkpoint = {
        "domain": "coding",
        "session_id": sid,
        "run_id": run_id,
        "user_prompt": "need ask",
        "repo_path": repo,
        "backend_name": "opencode",
        "tool_call_id": "call_ask_1",
        "ask_user_args": ask_args,
        "questions": [
            {
                "question_key": "q1",
                "question_type": "single_choice",
                "display_text": "which?",
                "choices": [{"value": "a", "label": "A"}, {"value": "other", "label": "その他（自由入力）"}],
                "is_required": 1,
                "sequence": 0,
            }
        ],
        "qa_history": [
            {
                "tool_call_id": "call_ask_1",
                "ask_user_args": ask_args,
                "answers": {"q1": {"selection": "a", "text": None}},
            }
        ],
        "resume_state": {"cli_count": 0, "phase": "initial", "phase_turn": 1},
        "phase": "initial",
        "phase_turn": 1,
        "cli_count": 0,
        "tool_ids": [],
        "provider": "openai",
        "model": "gpt-4o",
    }
    hitl_id = "hitl_ask_coding7777"
    hitl_service.register_run_and_questions(
        run_id=hitl_id,
        handler="coding.ask_user",
        checkpoint=json.dumps(checkpoint, ensure_ascii=False),
        question_set_id="qset_1",
        questions_data=checkpoint["questions"],
        title="t",
        description="d",
        display_type="in_conversation_question",
    )
    assert hitl_store.get_run(hitl_id) is not None

    orch = CodingOrchestrator(tool_ids=[])
    mock_llm, _, captured = _capture_llm()
    with (
        patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", return_value=mock_llm),
        patch("obsidian_ai_hub.agents.registry.resolve_tools_with_context", return_value=[]),
    ):
        async for _ in orch.generate_response_events(
            history=[{"role": "user", "content": "need ask"}],
            repo_path=repo,
            backend_name="opencode",
            hitl_run_id=hitl_id,
            session_id=sid,
            current_run_id=run_id,
        ):
            pass
    sys_content = _system_content(captured)
    assert "PRETOOL_CODING_777" in sys_content
    tool_msgs = [m for m in captured if isinstance(m, ToolMessage)]
    assert any("q1" in (m.content or "") for m in tool_msgs)


def test_load_prior_context_returns_completed_only_with_calls(coding_session):
    sess, _ = coding_session
    sid = sess["session_id"]
    r0 = _complete_run_with_calls(sid, "q0", [{"tool_name": "t", "result": "R0"}])
    _complete_run_with_calls(sid, "q1", [{"tool_name": "t", "result": "R1"}])
    prior, current = _load_prior_tool_context(sid, "crun_new")
    assert [p["run_id"] for p in prior] == [r0, prior[1]["run_id"]]
    assert current == []
    block = _build_prior_tool_results_block(prior, current)
    assert "R0" in block and "R1" in block
