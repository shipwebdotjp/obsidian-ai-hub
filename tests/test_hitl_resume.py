from __future__ import annotations

import sqlite3
import pytest
import uuid
from datetime import datetime, timezone, timedelta

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub import hitl


@pytest.fixture(autouse=True)
def clean_handlers_fixture():
    """Ensure the handler registry is clean before and after each test."""
    hitl.clear_handlers()
    yield
    hitl.clear_handlers()


def test_registry_and_handler_context(test_memory_db_path):
    """Verify that handlers can be registered, and they receive the proper context and answers."""
    conn = get_db_connection()
    try:
        run_id = "run_context_test"
        checkpoint = "initial_step"
        qset_id = "set_1"

        questions_data = [
            {
                "question_key": "user_choice",
                "question_type": "select",
                "display_text": "Do you want to continue?",
                "choices": ["yes", "no"],
                "is_required": 1,
            }
        ]

        # Register run & questions
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="dummy_handler",
            checkpoint=checkpoint,
            question_set_id=qset_id,
            questions_data=questions_data,
            conn=conn,
        )

        # Answer the question to make it ready_to_resume
        hitl.submit_answer(run_id, qset_id, "user_choice", "yes", conn)

        received_context = []

        def dummy_handler(ctx: hitl.HitlContext) -> hitl.HitlResult:
            received_context.append(ctx)
            return hitl.HitlResult.complete(checkpoint="step_completed")

        hitl.register_handler("dummy_handler", dummy_handler)

        # Dispatch
        count = hitl.dispatch_runs(conn)
        assert count == 1

        # Check handler received context
        assert len(received_context) == 1
        ctx = received_context[0]
        assert ctx.run_id == run_id
        assert ctx.checkpoint == checkpoint
        assert ctx.answers_by_question_key == {"user_choice": "yes"}

        # Check run status updated to completed
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "completed"
        assert run["checkpoint"] == "step_completed"
        assert run["lease_owner"] is None
        assert run["lease_expires_at"] is None
    finally:
        conn.close()


def test_handler_re_suspension_with_next_questions(test_memory_db_path):
    """Verify that a handler can register subsequent questions and return a re_suspended result."""
    conn = get_db_connection()
    try:
        run_id = "run_resuspend_test"
        qset_1 = "set_1"

        hitl.register_run_and_questions(
            run_id=run_id,
            handler="resuspend_handler",
            checkpoint="step_1",
            question_set_id=qset_1,
            questions_data=[
                {"question_key": "q1", "question_type": "text", "display_text": "Q1", "is_required": 1}
            ],
            conn=conn,
        )

        # Answer Q1 to make it ready to resume
        hitl.submit_answer(run_id, qset_1, "q1", "ans_1", conn)

        def resuspend_handler(ctx: hitl.HitlContext) -> hitl.HitlResult:
            # Register next question set within same transaction using context conn
            ctx.register_next_questions(
                question_set_id="set_2",
                questions_data=[
                    {"question_key": "q2", "question_type": "text", "display_text": "Q2", "is_required": 1}
                ],
                checkpoint="step_2_pending",
            )
            return hitl.HitlResult.re_suspend(checkpoint="step_2_pending")

        hitl.register_handler("resuspend_handler", resuspend_handler)

        # Dispatch
        count = hitl.dispatch_runs(conn)
        assert count == 1

        # Verify run is now pending_user with set_2 active and lease cleared
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "pending_user"
        assert run["active_question_set_id"] == "set_2"
        assert run["checkpoint"] == "step_2_pending"
        assert run["lease_owner"] is None
        assert run["lease_expires_at"] is None

        # Verify Q2 was inserted and is pending
        q2 = hitl.get_question(run_id, "set_2", "q2", conn)
        assert q2 is not None
        assert q2["status"] == "pending"
    finally:
        conn.close()


def test_handler_failure_records_error_and_increments_retry(test_memory_db_path):
    """Verify that a handler exception is caught, status is set to failed, and error message is saved."""
    conn = get_db_connection()
    try:
        run_id = "run_failure_test"
        qset_id = "set_1"

        hitl.register_run_and_questions(
            run_id=run_id,
            handler="failing_handler",
            checkpoint="start",
            question_set_id=qset_id,
            questions_data=[
                {"question_key": "q1", "question_type": "text", "display_text": "Q1", "is_required": 1}
            ],
            conn=conn,
        )

        hitl.submit_answer(run_id, qset_id, "q1", "value", conn)

        def failing_handler(ctx: hitl.HitlContext) -> hitl.HitlResult:
            raise RuntimeError("Something went wrong during execution!")

        hitl.register_handler("failing_handler", failing_handler)

        # Dispatch
        count = hitl.dispatch_runs(conn)
        assert count == 0  # no successful run processing because handler raised

        # Verify run failed, recorded error, incremented retry, and released lease
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "failed"
        assert "Something went wrong during execution!" in run["error_message"]
        assert run["retry_count"] == 1
        assert run["lease_owner"] is None
        assert run["lease_expires_at"] is None
    finally:
        conn.close()


def test_unregistered_handler_marks_failed(test_memory_db_path):
    """Verify that dispatching a run with an unregistered handler marks it as failed."""
    conn = get_db_connection()
    try:
        run_id = "run_unregistered"
        qset_id = "set_1"

        hitl.register_run_and_questions(
            run_id=run_id,
            handler="non_existent_handler",
            checkpoint="start",
            question_set_id=qset_id,
            questions_data=[
                {"question_key": "q1", "question_type": "text", "display_text": "Q1", "is_required": 1}
            ],
            conn=conn,
        )

        hitl.submit_answer(run_id, qset_id, "q1", "value", conn)

        # Dispatch without registering
        count = hitl.dispatch_runs(conn)
        assert count == 0

        # Verify run is marked failed
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "failed"
        assert "not registered" in run["error_message"]
    finally:
        conn.close()


def test_reclaim_expired_leases_and_repeated_execution_safety(test_memory_db_path):
    """Verify that expired running leases are reclaimable and checkpointed side effects support safe repeated execution."""
    conn = get_db_connection()
    try:
        run_id = "run_lease_reclaim"
        qset_id = "set_1"

        hitl.register_run_and_questions(
            run_id=run_id,
            handler="reclaim_handler",
            checkpoint="step_1_side_effect_done",
            question_set_id=qset_id,
            questions_data=[
                {"question_key": "q1", "question_type": "text", "display_text": "Q1", "is_required": 1}
            ],
            conn=conn,
        )

        hitl.submit_answer(run_id, qset_id, "q1", "done", conn)

        # First claim the run manually with worker_1
        hitl.claim_run(run_id, "worker_1", 30, conn)

        # Force lease to look expired in the DB
        past_iso = (datetime.now(timezone(timedelta(hours=9))) - timedelta(seconds=60)).isoformat()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE hitl_runs SET lease_expires_at = ? WHERE run_id = ?",
            (past_iso, run_id),
        )
        conn.commit()

        # Let's track how many times the side effect is executed
        side_effects_executed = []

        def reclaim_handler(ctx: hitl.HitlContext) -> hitl.HitlResult:
            # Safe repeated execution based on checkpoint!
            if ctx.checkpoint == "step_1_side_effect_done":
                # We skip step 1 side effects because checkpoint says they are already done!
                pass
            else:
                side_effects_executed.append("step_1")

            # Perform step 2 side effects
            side_effects_executed.append("step_2")
            return hitl.HitlResult.complete(checkpoint="step_2_completed")

        hitl.register_handler("reclaim_handler", reclaim_handler)

        # Dispatch should find and reclaim the run with expired lease
        count = hitl.dispatch_runs(conn)
        assert count == 1

        # Check side effects executed
        assert "step_1" not in side_effects_executed
        assert "step_2" in side_effects_executed

        # Check run completed
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "completed"
        assert run["checkpoint"] == "step_2_completed"
        assert run["lease_owner"] is None
    finally:
        conn.close()


def test_dispatch_cli_flag_processes_runs(test_memory_db_path, monkeypatch):
    """Invoking main() with --hitl-dispatch processes a ready_to_resume run to completion."""
    conn = get_db_connection()
    try:
        run_id = "run_cli_flag"
        qset_id = "set_cli"

        hitl.register_run_and_questions(
            run_id=run_id,
            handler="cli_handler",
            checkpoint="start",
            question_set_id=qset_id,
            questions_data=[
                {"question_key": "q1", "question_type": "text", "display_text": "Q1", "is_required": 1}
            ],
            conn=conn,
        )
        hitl.submit_answer(run_id, qset_id, "q1", "done", conn)

        def cli_handler(ctx: hitl.HitlContext) -> hitl.HitlResult:
            return hitl.HitlResult.complete(checkpoint="done")

        hitl.register_handler("cli_handler", cli_handler)

        monkeypatch.setattr("sys.argv", ["obsidian-ai-hub", "--hitl-dispatch"])
        from obsidian_ai_hub.main import main
        main()

        run = hitl.get_run(run_id, conn)
        assert run["status"] == "completed"
        assert run["checkpoint"] == "done"
    finally:
        conn.close()


def test_full_happy_path_dispatch(test_memory_db_path):
    """A run progresses through the complete lifecycle: pending_user → ready_to_resume → running → completed."""
    conn = get_db_connection()
    try:
        run_id = "run_happy_path"
        qset_id = "set_happy"

        hitl.register_run_and_questions(
            run_id=run_id,
            handler="happy_handler",
            checkpoint="chk",
            question_set_id=qset_id,
            questions_data=[
                {"question_key": "q1", "question_type": "text", "display_text": "Q1", "is_required": 1}
            ],
            conn=conn,
        )

        run = hitl.get_run(run_id, conn)
        assert run["status"] == "pending_user"

        hitl.submit_answer(run_id, qset_id, "q1", "value", conn)

        run = hitl.get_run(run_id, conn)
        assert run["status"] == "ready_to_resume"

        def happy_handler(ctx: hitl.HitlContext) -> hitl.HitlResult:
            return hitl.HitlResult.complete(checkpoint="chk_final")

        hitl.register_handler("happy_handler", happy_handler)
        count = hitl.dispatch_runs(conn)
        assert count == 1

        run = hitl.get_run(run_id, conn)
        assert run["status"] == "completed"
        assert run["checkpoint"] == "chk_final"
        assert run["lease_owner"] is None
        assert run["lease_expires_at"] is None
    finally:
        conn.close()


def test_dispatch_processes_multiple_runs_in_single_call(test_memory_db_path):
    """A single dispatch_runs call processes all eligible ready_to_resume runs."""
    conn = get_db_connection()
    try:
        run_ids = []
        for i in range(2):
            rid = f"run_multi_{i}"
            run_ids.append(rid)
            hitl.register_run_and_questions(
                run_id=rid,
                handler="multi_handler",
                checkpoint="chk",
                question_set_id=f"set_multi_{i}",
                questions_data=[
                    {"question_key": "q", "question_type": "text", "display_text": "Q", "is_required": 1}
                ],
                conn=conn,
            )
            hitl.submit_answer(rid, f"set_multi_{i}", "q", f"val_{i}", conn)

        def multi_handler(ctx: hitl.HitlContext) -> hitl.HitlResult:
            return hitl.HitlResult.complete(checkpoint="chk_done")

        hitl.register_handler("multi_handler", multi_handler)
        count = hitl.dispatch_runs(conn)
        assert count == 2

        for rid in run_ids:
            run = hitl.get_run(rid, conn)
            assert run["status"] == "completed"
    finally:
        conn.close()
