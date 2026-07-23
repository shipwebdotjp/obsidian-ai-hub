from __future__ import annotations

import sqlite3
import pytest
from datetime import datetime, timezone, timedelta

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub import hitl


def test_hitl_db_migration_and_structure(test_memory_db_path):
    """Verify that the database migration correctly creates hitl_runs and hitl_questions tables with proper constraints."""
    conn = get_db_connection()
    try:
        # Check database user_version is 13
        cursor = conn.cursor()
        cursor.execute("PRAGMA user_version;")
        version = cursor.fetchone()[0]
        assert version == 13

        # Verify hitl_runs columns
        cursor.execute("PRAGMA table_info(hitl_runs);")
        runs_cols = {row["name"]: row["type"] for row in cursor.fetchall()}
        assert "run_id" in runs_cols
        assert "handler" in runs_cols
        assert "status" in runs_cols
        assert "checkpoint" in runs_cols
        assert "active_question_set_id" in runs_cols
        assert "lease_owner" in runs_cols
        assert "lease_expires_at" in runs_cols
        assert "retry_count" in runs_cols
        assert "error_message" in runs_cols

        # Verify hitl_questions columns
        cursor.execute("PRAGMA table_info(hitl_questions);")
        questions_cols = {row["name"]: row["type"] for row in cursor.fetchall()}
        assert "question_id" in questions_cols
        assert "run_id" in questions_cols
        assert "question_set_id" in questions_cols
        assert "question_key" in questions_cols
        assert "status" in questions_cols
        assert "question_type" in questions_cols
        assert "display_text" in questions_cols
        assert "choices" in questions_cols
        assert "answer" in questions_cols
        assert "is_required" in questions_cols
        assert "expires_at" in questions_cols
        assert "answered_at" in questions_cols
    finally:
        conn.close()


def test_register_run_and_questions(test_memory_db_path):
    """Test registering a run and its initial question set."""
    conn = get_db_connection()
    try:
        run_id = "test_run_1"
        handler = "research"
        checkpoint = "step_1_init"
        question_set_id = "qset_1"

        questions_data = [
            {
                "question_key": "confirm_topic",
                "question_type": "boolean",
                "display_text": "Is the topic correct?",
                "choices": [True, False],
                "is_required": 1,
            },
            {
                "question_key": "notes",
                "question_type": "text",
                "display_text": "Any additional notes?",
                "is_required": 0,
            },
        ]

        hitl.register_run_and_questions(
            run_id=run_id,
            handler=handler,
            checkpoint=checkpoint,
            question_set_id=question_set_id,
            questions_data=questions_data,
            conn=conn,
        )

        # Retrieve and assert run
        run = hitl.get_run(run_id, conn)
        assert run is not None
        assert run["handler"] == handler
        assert run["status"] == "pending_user"
        assert run["checkpoint"] == checkpoint
        assert run["active_question_set_id"] == question_set_id

        # Retrieve questions
        questions = hitl.get_questions_by_set(run_id, question_set_id, conn)
        assert len(questions) == 2

        q_map = {q["question_key"]: q for q in questions}
        assert "confirm_topic" in q_map
        assert q_map["confirm_topic"]["status"] == "pending"
        assert q_map["confirm_topic"]["is_required"] == 1
        assert q_map["confirm_topic"]["choices"] == [True, False]

        assert "notes" in q_map
        assert q_map["notes"]["status"] == "pending"
        assert q_map["notes"]["is_required"] == 0
        assert q_map["notes"]["choices"] is None
    finally:
        conn.close()


def test_submit_answer_choice_validation_and_once_only(test_memory_db_path):
    """Test submitting answers, choice validations, and once-only answering constraint."""
    conn = get_db_connection()
    try:
        run_id = "run_choices"
        question_set_id = "qset_choices"
        questions_data = [
            {
                "question_key": "favorite_color",
                "question_type": "select",
                "display_text": "What is your favorite color?",
                "choices": ["red", "blue", "green"],
                "is_required": 1,
            }
        ]

        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test",
            checkpoint="init",
            question_set_id=question_set_id,
            questions_data=questions_data,
            conn=conn,
        )

        # Attempt to answer with invalid choice
        with pytest.raises(ValueError, match="is not a valid choice"):
            hitl.submit_answer(
                run_id=run_id,
                question_set_id=question_set_id,
                question_key="favorite_color",
                answer="purple",
                conn=conn,
            )

        # Answer with a valid choice
        hitl.submit_answer(
            run_id=run_id,
            question_set_id=question_set_id,
            question_key="favorite_color",
            answer="blue",
            conn=conn,
        )

        # Check question was updated
        q = hitl.get_question(run_id, question_set_id, "favorite_color", conn)
        assert q["status"] == "answered"
        assert q["answer"] == "blue"
        assert q["answered_at"] is not None

        # Check run status became ready_to_resume
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "ready_to_resume"

        # Attempt to answer the same question again
        with pytest.raises(ValueError, match="is already finalized"):
            hitl.submit_answer(
                run_id=run_id,
                question_set_id=question_set_id,
                question_key="favorite_color",
                answer="red",
                conn=conn,
            )
    finally:
        conn.close()


def test_required_vs_optional_questions(test_memory_db_path):
    """Verify state transitions when handling mixed required and optional questions."""
    conn = get_db_connection()
    try:
        run_id = "run_mixed"
        question_set_id = "qset_mixed"
        questions_data = [
            {
                "question_key": "required_q",
                "question_type": "text",
                "display_text": "Required question",
                "is_required": 1,
            },
            {
                "question_key": "optional_q",
                "question_type": "text",
                "display_text": "Optional question",
                "is_required": 0,
            }
        ]

        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test",
            checkpoint="start",
            question_set_id=question_set_id,
            questions_data=questions_data,
            conn=conn,
        )

        # Run should start as pending_user
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "pending_user"

        # Answer the optional question first
        hitl.submit_answer(
            run_id=run_id,
            question_set_id=question_set_id,
            question_key="optional_q",
            answer="Answered optional",
            conn=conn,
        )

        # Run must still be pending_user because the required question is pending
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "pending_user"

        # Answer the required question
        hitl.submit_answer(
            run_id=run_id,
            question_set_id=question_set_id,
            question_key="required_q",
            answer="Answered required",
            conn=conn,
        )

        # Run must now transition to ready_to_resume
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "ready_to_resume"
    finally:
        conn.close()


def test_claim_run_and_skip_optional(test_memory_db_path):
    """Test that claiming a run sets unanswered optional questions to 'skipped' and locks the run."""
    conn = get_db_connection()
    try:
        run_id = "run_claim"
        question_set_id = "qset_claim"
        questions_data = [
            {
                "question_key": "required_q",
                "question_type": "text",
                "display_text": "Required question",
                "is_required": 1,
            },
            {
                "question_key": "optional_q",
                "question_type": "text",
                "display_text": "Optional question",
                "is_required": 0,
            }
        ]

        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test",
            checkpoint="start",
            question_set_id=question_set_id,
            questions_data=questions_data,
            conn=conn,
        )

        # Cannot claim run in pending_user status
        claimed = hitl.claim_run(run_id, "worker_1", 60, conn)
        assert claimed is False

        # Answer the required question to make it ready_to_resume
        hitl.submit_answer(
            run_id=run_id,
            question_set_id=question_set_id,
            question_key="required_q",
            answer="Done",
            conn=conn,
        )

        run = hitl.get_run(run_id, conn)
        assert run["status"] == "ready_to_resume"

        # Claim the run now
        claimed = hitl.claim_run(run_id, "worker_1", 300, conn)
        assert claimed is True

        # Run must transition to 'running' with correct lease fields
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "running"
        assert run["lease_owner"] == "worker_1"
        assert run["lease_expires_at"] is not None

        # Unanswered optional question must be updated to 'skipped'
        optional_q = hitl.get_question(run_id, question_set_id, "optional_q", conn)
        assert optional_q["status"] == "skipped"
        assert optional_q["answer"] is None

        # Cannot claim again while lease is active
        claimed_again = hitl.claim_run(run_id, "worker_2", 300, conn)
        assert claimed_again is False
    finally:
        conn.close()


def test_claim_run_lease_expiration_reclaim(test_memory_db_path, monkeypatch):
    """Test that an expired lease on a running run can be reclaimed."""
    conn = get_db_connection()
    try:
        run_id = "run_lease_expiry"
        question_set_id = "qset_expiry"
        questions_data = [
            {
                "question_key": "q1",
                "question_type": "text",
                "display_text": "required",
                "is_required": 1,
            }
        ]

        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test",
            checkpoint="start",
            question_set_id=question_set_id,
            questions_data=questions_data,
            conn=conn,
        )

        hitl.submit_answer(run_id, question_set_id, "q1", "answered", conn)

        # Claim with very short duration (1 second)
        claimed = hitl.claim_run(run_id, "worker_1", 1, conn)
        assert claimed is True

        # Verify running
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "running"
        assert run["lease_owner"] == "worker_1"

        # Mock datetime so it appears lease is expired (e.g. 5 seconds in future)
        jst = timezone(timedelta(hours=9))
        future_now = datetime.now(jst) + timedelta(seconds=10)

        class MockedDatetime:
            @classmethod
            def now(cls, tz=None):
                return future_now
            @classmethod
            def fromisoformat(cls, val):
                return datetime.fromisoformat(val)

        monkeypatch.setattr("obsidian_ai_hub.hitl.service.datetime", MockedDatetime)

        # Try to reclaim with worker_2
        reclaimed = hitl.claim_run(run_id, "worker_2", 300, conn)
        assert reclaimed is True

        run = hitl.get_run(run_id, conn)
        assert run["lease_owner"] == "worker_2"
    finally:
        conn.close()


def test_cancel_run(test_memory_db_path):
    """Test cancelling a run updates run status to 'cancelled' and cancels pending questions."""
    conn = get_db_connection()
    try:
        run_id = "run_cancel"
        question_set_id = "qset_cancel"
        questions_data = [
            {
                "question_key": "q_req",
                "question_type": "text",
                "display_text": "Required",
                "is_required": 1,
            },
            {
                "question_key": "q_opt",
                "question_type": "text",
                "display_text": "Optional",
                "is_required": 0,
            }
        ]

        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test",
            checkpoint="start",
            question_set_id=question_set_id,
            questions_data=questions_data,
            conn=conn,
        )

        # Answer required question
        hitl.submit_answer(run_id, question_set_id, "q_req", "Answer", conn)

        # Cancel the run while optional is still pending
        hitl.cancel_run(run_id, conn)

        # Verify run status
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "cancelled"

        # Verify q_req remains 'answered', but q_opt became 'cancelled'
        q_req = hitl.get_question(run_id, question_set_id, "q_req", conn)
        assert q_req["status"] == "answered"

        q_opt = hitl.get_question(run_id, question_set_id, "q_opt", conn)
        assert q_opt["status"] == "cancelled"
    finally:
        conn.close()


def test_checkpoint_updates(test_memory_db_path):
    """Test updating the run checkpoint, retry count, and error messages."""
    conn = get_db_connection()
    try:
        run_id = "run_checkpoint"
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test",
            checkpoint="init",
            question_set_id="qs1",
            questions_data=[],
            conn=conn,
        )

        run = hitl.get_run(run_id, conn)
        assert run["checkpoint"] == "init"
        assert run["retry_count"] == 0
        assert run["error_message"] is None

        # Update checkpoint and retry count
        hitl.update_checkpoint(
            run_id=run_id,
            checkpoint="step_2_checkpoint",
            error_message="Transient error occurred",
            retry_count_delta=1,
            conn=conn,
        )

        run = hitl.get_run(run_id, conn)
        assert run["checkpoint"] == "step_2_checkpoint"
        assert run["retry_count"] == 1
        assert run["error_message"] == "Transient error occurred"
    finally:
        conn.close()


def test_multiple_question_sets_and_unique_constraint(test_memory_db_path):
    """Verify multiple question sets are registered and unique constraint on (run_id, set_id, key) prevents duplicates."""
    conn = get_db_connection()
    try:
        run_id = "run_multi_set"

        # Register Set 1
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test",
            checkpoint="c1",
            question_set_id="set_1",
            questions_data=[
                {"question_key": "q_key", "question_type": "text", "display_text": "S1 Q"}
            ],
            conn=conn,
        )

        # Register Set 2 for the same run
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test",
            checkpoint="c2",
            question_set_id="set_2",
            questions_data=[
                {"question_key": "q_key", "question_type": "text", "display_text": "S2 Q"}
            ],
            conn=conn,
        )

        run = hitl.get_run(run_id, conn)
        assert run["active_question_set_id"] == "set_2"
        assert run["checkpoint"] == "c2"

        # Verify we can fetch both questions (they have different question_set_id)
        q1 = hitl.get_question(run_id, "set_1", "q_key", conn)
        q2 = hitl.get_question(run_id, "set_2", "q_key", conn)
        assert q1 is not None
        assert q1["display_text"] == "S1 Q"
        assert q2 is not None
        assert q2["display_text"] == "S2 Q"

        # Verify that inserting same run_id, set_id, question_key fails
        with pytest.raises(sqlite3.IntegrityError):
            hitl.store.insert_question({
                "run_id": run_id,
                "question_set_id": "set_2",
                "question_key": "q_key",
                "status": "pending",
                "question_type": "text",
                "display_text": "Duplicate Q"
            }, conn)
    finally:
        conn.close()


def test_register_run_and_questions_idempotence(test_memory_db_path):
    """Verify that register_run_and_questions is idempotent and preserves question_ids."""
    conn = get_db_connection()
    try:
        run_id = "run_idemp"
        qset_id = "qset_idemp"
        questions_data = [
            {"question_key": "q1", "question_type": "text", "display_text": "Original text", "is_required": 1}
        ]

        # First registration
        hitl.register_run_and_questions(run_id, "test", "c1", qset_id, questions_data, conn)
        q1_first = hitl.get_question(run_id, qset_id, "q1", conn)
        assert q1_first is not None
        assert q1_first["display_text"] == "Original text"
        assert q1_first["status"] == "pending"

        # Submit answer to q1
        hitl.submit_answer(run_id, qset_id, "q1", "Answer content", conn)
        q1_ans = hitl.get_question(run_id, qset_id, "q1", conn)
        assert q1_ans["status"] == "answered"

        # Second registration with modified display_text
        questions_data_mod = [
            {"question_key": "q1", "question_type": "text", "display_text": "Updated text", "is_required": 1}
        ]
        hitl.register_run_and_questions(run_id, "test", "c1", qset_id, questions_data_mod, conn)

        # Retrieve again: question_id, status, and answer must be preserved!
        q1_second = hitl.get_question(run_id, qset_id, "q1", conn)
        assert q1_second["question_id"] == q1_first["question_id"]
        assert q1_second["status"] == "answered"
        assert q1_second["answer"] == "Answer content"
        assert q1_second["display_text"] == "Updated text"
    finally:
        conn.close()


def test_submit_answer_rejects_historical_inactive_sets(test_memory_db_path):
    """Verify that submit_answer rejects answers targeting historical/inactive question sets."""
    conn = get_db_connection()
    try:
        run_id = "run_hist"

        # Register Set 1
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test",
            checkpoint="c1",
            question_set_id="set_1",
            questions_data=[
                {"question_key": "q", "question_type": "text", "display_text": "Q1", "is_required": 1}
            ],
            conn=conn,
        )

        # Register Set 2 (making Set 2 the active set)
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="test",
            checkpoint="c2",
            question_set_id="set_2",
            questions_data=[
                {"question_key": "q", "question_type": "text", "display_text": "Q2", "is_required": 1}
            ],
            conn=conn,
        )

        # Attempt to answer the question from the historical set_1
        with pytest.raises(ValueError, match="Cannot submit answer for inactive or historical question set"):
            hitl.submit_answer(run_id, "set_1", "q", "some answer", conn)

        # Answering the active set_2 must succeed
        hitl.submit_answer(run_id, "set_2", "q", "active answer", conn)
        q2 = hitl.get_question(run_id, "set_2", "q", conn)
        assert q2["status"] == "answered"
        assert q2["answer"] == "active answer"
    finally:
        conn.close()


def test_choices_and_answer_serialization_symmetry(test_memory_db_path):
    """Test that choices and answer fields serialize and deserialize symmetrically (e.g. including plain strings)."""
    conn = get_db_connection()
    try:
        run_id = "run_sym"
        qset_id = "qset_sym"
        questions_data = [
            {
                "question_key": "q",
                "question_type": "select",
                "display_text": "Symmetric selection",
                "choices": ["yes", "no"],
                "is_required": 1,
            }
        ]

        hitl.register_run_and_questions(run_id, "test", "c1", qset_id, questions_data, conn)

        # Verify choices deserialized as a Python list
        q = hitl.get_question(run_id, qset_id, "q", conn)
        assert q["choices"] == ["yes", "no"]

        # Submit a plain string answer (should be JSON-encoded on save and decoded on load as a string)
        hitl.submit_answer(run_id, qset_id, "q", "yes", conn)

        q_ans = hitl.get_question(run_id, qset_id, "q", conn)
        assert q_ans["answer"] == "yes"
    finally:
        conn.close()


def test_submit_answer_concurrent_conflict(test_memory_db_path):
    """Test that concurrent/repeated submit_answer calls on two distinct connections result in only one success and one conflict."""
    # We open two completely distinct sqlite3 connections to the same isolated DB file
    conn1 = get_db_connection()
    conn2 = sqlite3.connect(str(test_memory_db_path), check_same_thread=False, timeout=30.0)
    conn2.row_factory = sqlite3.Row
    conn2.execute("PRAGMA foreign_keys = ON;")

    try:
        run_id = "run_concurrent"
        qset_id = "qset_concurrent"
        questions_data = [
            {"question_key": "q1", "question_type": "text", "display_text": "Concurrent Q", "is_required": 1}
        ]

        # Register using conn1
        hitl.register_run_and_questions(run_id, "test", "c1", qset_id, questions_data, conn1)

        # Call submit_answer on conn1 (first connection). This must succeed.
        hitl.submit_answer(run_id, qset_id, "q1", "First Answer", conn1)

        # Now attempt to answer on conn2 (second connection).
        # This must raise a ValueError (Conflict detected) because the status is no longer 'pending'
        with pytest.raises(ValueError, match="Conflict detected|already finalized"):
            hitl.submit_answer(run_id, qset_id, "q1", "Second Answer", conn2)

        # Verify that the answer saved in DB remains "First Answer"
        q = hitl.get_question(run_id, qset_id, "q1", conn1)
        assert q["status"] == "answered"
        assert q["answer"] == "First Answer"
    finally:
        conn1.close()
        conn2.close()
