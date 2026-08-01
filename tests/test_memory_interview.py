from __future__ import annotations

import json
import pytest
import sqlite3
from datetime import datetime, timezone, timedelta

from obsidian_ai_hub import hitl
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.memory.interview import (
    get_next_monday_morning,
    generate_interview_questions,
    apply_interview_answers,
)
from obsidian_ai_hub.hitl.dispatcher import HitlContext, HitlResult, dispatch_runs
from obsidian_ai_hub.utils import config


def test_hitl_question_expiration_and_cancellation(test_memory_db_path):
    """
    Test generic HITL expiration logic where expired required question cancels the run,
    and expired optional question is skipped.
    """
    conn = get_db_connection()
    try:
        run_id = "test_run_expiry"
        # Register a run with required and optional questions
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test_handler",
            checkpoint="c1",
            question_set_id="set_1",
            questions_data=[
                {
                    "question_key": "req_q",
                    "question_type": "text",
                    "display_text": "Required Q",
                    "is_required": 1,
                    "expires_at": "2026-01-01T09:00:00+09:00",  # Expired
                },
                {
                    "question_key": "opt_q",
                    "question_type": "text",
                    "display_text": "Optional Q",
                    "is_required": 0,
                    "expires_at": "2026-01-01T09:00:00+09:00",  # Expired
                }
            ],
            conn=conn,
            title="Expiry test",
            display_type="test",
        )

        # Dispatch should process expired questions and cancel the run because of the required question
        processed = dispatch_runs(conn)
        assert processed == 0  # No runs executed, but expiration processed

        run = hitl.get_run(run_id, conn)
        assert run["status"] == "cancelled"

        q_req = hitl.get_question(run_id, "set_1", "req_q", conn)
        q_opt = hitl.get_question(run_id, "set_1", "opt_q", conn)
        assert q_req["status"] == "cancelled"
        assert q_opt["status"] == "cancelled"  # All pending questions cancelled on run cancel
    finally:
        conn.close()


def test_hitl_optional_question_expiration_skips(test_memory_db_path):
    """
    Test that expired optional question is skipped, and if no pending required questions remain,
    the run becomes ready_to_resume.
    """
    conn = get_db_connection()
    try:
        # Register a mock handler to avoid 'Handler not registered' failure
        from obsidian_ai_hub.hitl.dispatcher import register_handler, HitlResult
        register_handler("test_expiry_handler", lambda ctx: HitlResult.complete())

        run_id = "test_run_expiry_opt"
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test_expiry_handler",
            checkpoint="c1",
            question_set_id="set_1",
            questions_data=[
                {
                    "question_key": "opt_q",
                    "question_type": "text",
                    "display_text": "Optional Q",
                    "is_required": 0,
                    "expires_at": "2026-01-01T09:00:00+09:00",  # Expired
                }
            ],
            conn=conn,
            title="Expiry test opt",
            display_type="test",
        )

        # Dispatch should process expiration and transition the run to ready_to_resume
        dispatch_runs(conn)

        run = hitl.get_run(run_id, conn)
        # Note: Once it becomes ready_to_resume, dispatch_runs also runs the claimed handler,
        # which returns HitlResult.complete() making the run status "completed".
        assert run["status"] == "completed"

        q_opt = hitl.get_question(run_id, "set_1", "opt_q", conn)
        assert q_opt["status"] == "skipped"
    finally:
        conn.close()


def test_next_monday_calculation():
    """Test get_next_monday_morning calculates correct next monday 09:00:00 JST."""
    jst = timezone(timedelta(hours=9))
    # A Wednesday JST
    wed = datetime(2026, 7, 29, 12, 0, 0, tzinfo=jst)
    next_mon = get_next_monday_morning(wed)
    # Next Monday is 2026-08-03
    assert next_mon == "2026-08-03T09:00:00+09:00"

    # A Monday morning before 09:00 (should go to next monday)
    mon_early = datetime(2026, 7, 27, 8, 0, 0, tzinfo=jst)
    next_mon_from_early = get_next_monday_morning(mon_early)
    assert next_mon_from_early == "2026-08-03T09:00:00+09:00"

    # A non-JST timezone aware datetime such as UTC: Wednesday JST is still Wednesday UTC
    utc_wed = datetime(2026, 7, 29, 3, 0, 0, tzinfo=timezone.utc)  # corresponds to 2026-07-29T12:00:00+09:00 JST
    next_mon_from_utc = get_next_monday_morning(utc_wed)
    assert next_mon_from_utc == "2026-08-03T09:00:00+09:00"


def test_generate_interview_questions_idempotence(test_memory_db_path, monkeypatch):
    """Test that generating interview questions creates a HITL Run and is idempotent."""
    conn = get_db_connection()
    try:
        # Mock LLM response
        mock_resp = json.dumps([
            {
                "question_key": "coffee_preference",
                "title": "コーヒーの好み",
                "prompt": "朝どのようなコーヒーを飲みますか？",
                "context": {"category": "preference", "reasoning": "Test reasoning"}
            }
        ])
        monkeypatch.setattr("obsidian_ai_hub.utils.llm_client.generate_llm_response", lambda *a, **kw: mock_resp)

        # Create dummy source daily note to satisfy file reading check
        # We need to mock _load_weekly_memory_sources to return dummy data
        monkeypatch.setattr(
            "obsidian_ai_hub.memory.interview._load_weekly_memory_sources",
            lambda start, end: ([{"date": "2026-07-27", "path": "daily/2026-07-27.md", "content": "## 📝メモ\n珈琲飲んだ。"}], [])
        )

        generate_interview_questions("2026-07-30")

        # Verify run registered
        run = hitl.get_run("mem_interview_2026-W31", conn)
        assert run is not None
        assert run["display_type"] == "interview"
        assert run["title"] == "週次メモリインタビュー"

        questions = hitl.get_questions_by_set("mem_interview_2026-W31", "initial", conn)
        assert len(questions) == 1
        assert questions[0]["question_key"] == "coffee_preference"
        assert questions[0]["prompt"] == "朝どのようなコーヒーを飲みますか？"

        # Attempt to generate again, should skip (idempotency check)
        monkeypatch.setattr("obsidian_ai_hub.utils.llm_client.generate_llm_response", lambda *a, **kw: "[]")
        generate_interview_questions("2026-07-30")
        questions_after = hitl.get_questions_by_set("mem_interview_2026-W31", "initial", conn)
        assert len(questions_after) == 1  # Still 1, didn't overwrite
    finally:
        conn.close()


def test_apply_interview_answers_flow(test_memory_db_path, monkeypatch):
    """Test full interview answers processing flow with deduplication and DB saving."""
    conn = get_db_connection()
    try:
        # Register a completed interview Run
        run_id = "mem_interview_2026-W31"
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="memory.apply_interview_answers",
            checkpoint=json.dumps({"source_week_start": "2026-07-27", "source_week_end": "2026-08-02"}),
            question_set_id="initial",
            questions_data=[
                {
                    "question_key": "coffee_pref",
                    "question_type": "text",
                    "display_text": "Coffee pref?",
                    "is_required": 1,
                    "title": "コーヒーの好み",
                    "prompt": "コーヒーの好み？",
                }
            ],
            conn=conn,
            title="Interview Test",
            display_type="interview"
        )

        # Submit answer
        hitl.submit_answer(run_id, "initial", "coffee_pref", "朝は深煎りのコロンビア産コーヒーを好む。", conn)

        # Mock candidate extraction LLM response
        candidate_mock_resp = json.dumps([
            {
                "kind": "preference",
                "memory_key": "coffeeColombiaPref",
                "content": "朝は深煎りのコロンビア産コーヒーを好んで飲む。",
                "topics": ["趣味", "習慣"],
                "tags": [],
                "stability": "tentative"
            }
        ])
        monkeypatch.setattr("obsidian_ai_hub.utils.llm_client.generate_llm_response", lambda *a, **kw: candidate_mock_resp)

        # Execute dispatch
        from obsidian_ai_hub.main import register_hitl_handlers
        register_hitl_handlers()

        processed = dispatch_runs(conn)
        assert processed == 1

        # Check run completed
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "completed"

        # Check candidate memory saved
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE status = 'candidate'")
        mems = cursor.fetchall()
        assert len(mems) == 1
        memory_row = dict(mems[0])
        assert memory_row["memory_key"] == "coffeeColombiaPref"
        assert memory_row["content"] == "朝は深煎りのコロンビア産コーヒーを好んで飲む。"

        # Check evidence saved
        evidence = json.loads(memory_row["evidence"])
        assert len(evidence) == 1
        assert evidence[0]["path"] == "hitl://runs/mem_interview_2026-W31/questions/coffee_pref"
        assert evidence[0]["quote"] == "朝は深煎りのコロンビア産コーヒーを好む。"
    finally:
        conn.close()


def test_apply_interview_answers_failure_rollback(test_memory_db_path, monkeypatch):
    """Test that LLM extraction failure fails the run and registers no partial candidate memories."""
    conn = get_db_connection()
    try:
        run_id = "mem_interview_2026-W32"
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="memory.apply_interview_answers",
            checkpoint=json.dumps({"source_week_start": "2026-08-03", "source_week_end": "2026-08-09"}),
            question_set_id="initial",
            questions_data=[
                {
                    "question_key": "coffee_pref",
                    "question_type": "text",
                    "display_text": "Coffee pref?",
                    "is_required": 1,
                    "title": "コーヒーの好み",
                    "prompt": "コーヒーの好み？",
                }
            ],
            conn=conn,
            title="Interview Rollback Test",
            display_type="interview"
        )

        hitl.submit_answer(run_id, "initial", "coffee_pref", "コロンビア豆が好き", conn)

        # Mock LLM failure
        def mock_llm_fail(*args, **kwargs):
            raise RuntimeError("LLM network timeout!")

        monkeypatch.setattr("obsidian_ai_hub.utils.llm_client.generate_llm_response", mock_llm_fail)

        from obsidian_ai_hub.main import register_hitl_handlers
        register_hitl_handlers()

        dispatch_runs(conn)

        # Run should be marked as failed
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "failed"
        assert "LLM call failed" in run["error_message"]

        # Ensure NO memories were created in DB
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM memories")
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()
