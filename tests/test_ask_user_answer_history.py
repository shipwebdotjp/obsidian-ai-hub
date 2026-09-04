"""Unit and integration tests for ask_user_answer_history extraction and API response."""

import json
import pytest
from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.agents.ask_user import extract_session_ask_user_history
from obsidian_ai_hub.agents.ask_user_handler import handle_agent_ask_user, handle_coding_ask_user
from obsidian_ai_hub.coding import store as coding_store
from obsidian_ai_hub.hitl import service as hitl_service, store as hitl_store
from obsidian_ai_hub.hitl.dispatcher import HitlContext
from obsidian_ai_hub.web.services import agents as agent_web_service


@pytest.fixture
def agent_session_setup(tmp_path):
    """Create test agent and session."""
    agent = agent_store.create_agent(
        name="Test History Agent",
        system_prompt="You are a helpful assistant.",
        tool_ids=["ask_user"],
    )
    session = agent_store.create_session(agent_id=agent["agent_id"])
    return agent, session


@pytest.fixture
def coding_session_setup(tmp_path):
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
        " VALUES ('history-proj', 'History Proj', 'personal', 'active', ?, datetime('now'), datetime('now'));",
        (str(repo),),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()

    session = coding_store.create_session(
        project_id=pid,
        backend="codex",
        repo_path=str(repo),
        title="History Coding Session",
    )
    return session


def test_extract_session_ask_user_history_single_and_multi_round(agent_session_setup):
    """Verify answer history extraction across multiple rounds and user messages."""
    agent, session = agent_session_setup
    session_id = session["session_id"]

    # 1. User message 1 -> ask_user round 1
    msg1, run1 = agent_store.start_queued_run(session_id, "第一の確認")
    user_msg_id1 = msg1["message_id"]
    run_id1 = run1["run_id"]
    hitl_id1 = "hitl_ask_test1"

    questions_data1 = [
        {
            "question_key": "q_target",
            "question_type": "single_choice",
            "display_text": "対象サービスを選択してください",
            "choices": [
                {"value": "web", "label": "Web画面"},
                {"value": "api", "label": "APIサーバー"},
                {"value": "other", "label": "その他（自由入力）"},
            ],
            "is_required": 1,
            "sequence": 0,
        }
    ]
    cp1 = {
        "domain": "agent",
        "agent_id": agent["agent_id"],
        "session_id": session_id,
        "run_id": run_id1,
        "user_content": "第一の確認",
        "tool_call_id": "call_1",
        "ask_user_args": {
            "questions": [
                {
                    "question_id": "q_target",
                    "question": "対象サービスを選択してください",
                    "choices": [
                        {"value": "web", "label": "Web画面"},
                        {"value": "api", "label": "APIサーバー"},
                    ],
                }
            ]
        },
        "questions": questions_data1,
        "qa_history": [],
    }

    hitl_service.register_run_and_questions(
        run_id=hitl_id1,
        handler="agents.ask_user",
        checkpoint=json.dumps(cp1, ensure_ascii=False),
        question_set_id="qset_1",
        questions_data=questions_data1,
        title="会話内の要件確認",
        description="確認質問",
        display_type="in_conversation_question",
    )
    agent_store.update_run_hitl(run_id=run_id1, status="waiting_user", hitl_run_id=hitl_id1)

    # User answers round 1 with 'other' and free text
    hitl_service.submit_answer(
        run_id=hitl_id1,
        question_set_id="qset_1",
        question_key="q_target",
        answer={"value": "other", "comment": "バッチ処理"},
    )
    ctx1 = HitlContext(
        run_id=hitl_id1,
        checkpoint=json.dumps(cp1, ensure_ascii=False),
        answers_by_question_key={"q_target": "other"},
        conn=None,
        raw_answers_by_question_key={"q_target": {"value": "other", "comment": "バッチ処理"}},
    )
    res1 = handle_agent_ask_user(ctx1)
    hitl_service.update_checkpoint(hitl_id1, res1.checkpoint)

    # 2. Same user message 1 -> ask_user round 2 (multi-round under same user_message_id)
    hitl_id2 = "hitl_ask_test2"
    cp2 = json.loads(res1.checkpoint)
    cp2["tool_call_id"] = "call_2"
    cp2["ask_user_args"] = {
        "questions": [
            {
                "question_id": "q_env",
                "question": "環境を選択してください",
                "choices": [
                    {"value": "dev", "label": "開発環境"},
                    {"value": "prod", "label": "本番環境"},
                ],
            }
        ]
    }
    cp2["questions"] = [
        {
            "question_key": "q_env",
            "question_type": "single_choice",
            "display_text": "環境を選択してください",
            "choices": [
                {"value": "dev", "label": "開発環境"},
                {"value": "prod", "label": "本番環境"},
                {"value": "other", "label": "その他（自由入力）"},
            ],
            "is_required": 1,
            "sequence": 0,
        }
    ]

    hitl_service.register_run_and_questions(
        run_id=hitl_id2,
        handler="agents.ask_user",
        checkpoint=json.dumps(cp2, ensure_ascii=False),
        question_set_id="qset_1",
        questions_data=cp2["questions"],
        title="会話内の要件確認",
        description="確認質問2",
        display_type="in_conversation_question",
    )
    agent_store.update_run_hitl(run_id=run_id1, status="waiting_user", hitl_run_id=hitl_id2)

    hitl_service.submit_answer(
        run_id=hitl_id2,
        question_set_id="qset_1",
        question_key="q_env",
        answer={"value": "dev", "comment": None},
    )
    ctx2 = HitlContext(
        run_id=hitl_id2,
        checkpoint=json.dumps(cp2, ensure_ascii=False),
        answers_by_question_key={"q_env": "dev"},
        conn=None,
        raw_answers_by_question_key={"q_env": {"value": "dev", "comment": None}},
    )
    res2 = handle_agent_ask_user(ctx2)
    hitl_service.update_checkpoint(hitl_id2, res2.checkpoint)

    # Fetch session detail
    detail = agent_web_service.get_session_detail(session_id)
    history = detail.get("ask_user_answer_history")
    assert isinstance(history, list)
    assert len(history) == 2

    # Round 1 verification
    r1 = history[0]
    assert r1["user_message_id"] == user_msg_id1
    assert r1["hitl_run_id"] == hitl_id2
    assert r1["tool_call_id"] == "call_1"
    assert len(r1["items"]) == 1
    assert r1["items"][0]["question_id"] == "q_target"
    assert r1["items"][0]["selected_value"] == "other"
    assert r1["items"][0]["selected_label"] == "その他（自由入力）"
    assert r1["items"][0]["text"] == "バッチ処理"

    # Round 2 verification
    r2 = history[1]
    assert r2["user_message_id"] == user_msg_id1
    assert r2["hitl_run_id"] == hitl_id2
    assert r2["tool_call_id"] == "call_2"
    assert len(r2["items"]) == 1
    assert r2["items"][0]["question_id"] == "q_env"
    assert r2["items"][0]["selected_value"] == "dev"
    assert r2["items"][0]["selected_label"] == "開発環境"
    assert r2["items"][0]["text"] is None


def test_extract_session_ask_user_history_v1_and_exclusions(agent_session_setup):
    """Verify v1 checkpoint normalization, non-ask_user HITL exclusion, and unanswered HITL exclusion."""
    agent, session = agent_session_setup
    session_id = session["session_id"]

    # 1. v1 checkpoint ask_user run
    msg1, run1 = agent_store.start_queued_run(session_id, "v1テスト")
    run_id1 = run1["run_id"]
    hitl_v1_id = "hitl_v1_ask"
    cp_v1 = {
        "domain": "agent",
        "run_id": run_id1,
        "tool_call_id": "call_v1",
        "ask_user_args": {
            "questions": [
                {
                    "question_id": "q_v1",
                    "question": "v1質問",
                    "choices": [{"value": "opt1", "label": "選択肢1"}],
                }
            ]
        },
        "answers": {"q_v1": {"selection": "opt1", "text": None}},
    }
    hitl_service.register_run_and_questions(
        run_id=hitl_v1_id,
        handler="agents.ask_user",
        checkpoint=json.dumps(cp_v1, ensure_ascii=False),
        question_set_id="qset_1",
        questions_data=[],
        title="v1質問",
        display_type="in_conversation_question",
    )
    agent_store.update_run_hitl(run_id=run_id1, status="succeeded", hitl_run_id=hitl_v1_id)

    # 2. Non-ask_user HITL run (e.g. research_suggestion)
    msg2, run2 = agent_store.start_queued_run(session_id, "リサーチテスト")
    run_id2 = run2["run_id"]
    hitl_other_id = "hitl_other_type"
    hitl_service.register_run_and_questions(
        run_id=hitl_other_id,
        handler="research.run_approved_suggestion",
        checkpoint=json.dumps({"theme_id": "t1"}, ensure_ascii=False),
        question_set_id="qset_1",
        questions_data=[],
        title="他タイプHITL",
        display_type="generic",
    )
    agent_store.update_run_hitl(run_id=run_id2, status="succeeded", hitl_run_id=hitl_other_id)

    # 3. Unanswered pending ask_user HITL run
    msg3, run3 = agent_store.start_queued_run(session_id, "未回答テスト")
    run_id3 = run3["run_id"]
    hitl_pending_id = "hitl_pending_ask"
    cp_pending = {
        "domain": "agent",
        "run_id": run_id3,
        "tool_call_id": "call_pending",
        "ask_user_args": {
            "questions": [{"question_id": "q_p", "question": "未回答?", "choices": [{"value": "a", "label": "A"}]}]
        },
        # No answers / qa_history is empty
    }
    hitl_service.register_run_and_questions(
        run_id=hitl_pending_id,
        handler="agents.ask_user",
        checkpoint=json.dumps(cp_pending, ensure_ascii=False),
        question_set_id="qset_1",
        questions_data=[],
        title="未回答質問",
        display_type="in_conversation_question",
    )
    agent_store.update_run_hitl(run_id=run_id3, status="waiting_user", hitl_run_id=hitl_pending_id)

    runs = agent_store.list_runs(session_id)
    history = extract_session_ask_user_history(runs)

    # Only v1 answered run should appear in history
    assert len(history) == 1
    assert history[0]["hitl_run_id"] == hitl_v1_id
    assert history[0]["user_message_id"] == msg1["message_id"]
    assert history[0]["items"][0]["question_id"] == "q_v1"
    assert history[0]["items"][0]["selected_value"] == "opt1"
    assert history[0]["items"][0]["selected_label"] == "選択肢1"


def test_coding_session_ask_user_history(coding_session_setup):
    """Verify Coding Workspace session detail includes ask_user_answer_history."""
    session = coding_session_setup
    session_id = session["session_id"]

    _, run = coding_store.start_queued_run(session_id, "Coding質問")
    user_msg_id = run["user_message_id"]
    run_id = run["run_id"]
    hitl_id = "hitl_coding_ask"

    questions_data = [
        {
            "question_key": "q_mode",
            "question_type": "single_choice",
            "display_text": "動作モード",
            "choices": [
                {"value": "fast", "label": "高速"},
                {"value": "full", "label": "完全"},
            ],
            "is_required": 1,
            "sequence": 0,
        }
    ]
    cp = {
        "domain": "coding",
        "run_id": run_id,
        "tool_call_id": "call_c1",
        "ask_user_args": {
            "questions": [
                {
                    "question_id": "q_mode",
                    "question": "動作モード",
                    "choices": [
                        {"value": "fast", "label": "高速"},
                        {"value": "full", "label": "完全"},
                    ],
                }
            ]
        },
        "questions": questions_data,
        "qa_history": [],
    }

    hitl_service.register_run_and_questions(
        run_id=hitl_id,
        handler="coding.ask_user",
        checkpoint=json.dumps(cp, ensure_ascii=False),
        question_set_id="qset_1",
        questions_data=questions_data,
        title="Coding要件確認",
        display_type="in_conversation_question",
    )
    coding_store.update_run(run_id=run_id, status="waiting_user", hitl_run_id=hitl_id)

    hitl_service.submit_answer(
        run_id=hitl_id,
        question_set_id="qset_1",
        question_key="q_mode",
        answer={"value": "fast", "comment": None},
    )
    ctx = HitlContext(
        run_id=hitl_id,
        checkpoint=json.dumps(cp, ensure_ascii=False),
        answers_by_question_key={"q_mode": "fast"},
        conn=None,
        raw_answers_by_question_key={"q_mode": {"value": "fast", "comment": None}},
    )
    res = handle_coding_ask_user(ctx)
    hitl_service.update_checkpoint(hitl_id, res.checkpoint)

    # Fetch coding session detail via store/service
    runs = coding_store.list_runs_for_session(session_id)
    history = extract_session_ask_user_history(runs)
    assert len(history) == 1
    assert history[0]["user_message_id"] == user_msg_id
    assert history[0]["hitl_run_id"] == hitl_id
    assert history[0]["items"][0]["question_id"] == "q_mode"
    assert history[0]["items"][0]["selected_label"] == "高速"
