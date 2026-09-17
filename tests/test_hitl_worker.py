from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

import pytest

from obsidian_ai_hub.hitl.dispatcher import (
    HitlContext,
    HitlResult,
    clear_handlers,
    register_handler,
)
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl.service import (
    claim_run,
    get_current_iso,
    register_run_and_questions,
    renew_lease_heartbeat,
    settle_run_outcome,
    submit_answer,
)
import threading
from obsidian_ai_hub.hitl.store import get_run
from obsidian_ai_hub.main import main
from obsidian_ai_hub.hitl.worker import HitlWorker


@pytest.fixture(autouse=True)
def cleanup_hitl_handlers():
    clear_handlers()
    yield
    clear_handlers()


def test_renew_lease_heartbeat_ownership_and_expiration(test_memory_db_path):
    """Test renew_lease_heartbeat under valid and invalid ownership/expiration conditions."""
    conn = get_db_connection()
    run_id = "run_hb_test"
    questions = [
        {"question_key": "q1", "question_type": "text", "display_text": "Q1", "is_required": 1}
    ]
    register_run_and_questions(
        run_id=run_id,
        handler="dummy_handler",
        checkpoint=None,
        question_set_id="set_1",
        questions_data=questions,
        title="HB Test Run",
        display_type="test",
        conn=conn,
    )

    # Transition run to ready_to_resume before claiming
    submit_answer(run_id, "set_1", "q1", answer="val", conn=conn)

    # Claim run
    worker_id = "worker_1"
    claimed = claim_run(run_id, worker_id, lease_duration_seconds=300, conn=conn)
    assert claimed is True

    # Valid heartbeat renewal
    renewed = renew_lease_heartbeat(
        run_id=run_id, lease_owner=worker_id, extension_seconds=300, conn=conn
    )
    assert renewed is True

    run_after = get_run(run_id, conn)
    assert run_after["lease_owner"] == worker_id
    assert run_after["lease_expires_at"] > get_current_iso()

    # Heartbeat renewal with wrong worker_id should fail
    renewed_wrong_owner = renew_lease_heartbeat(
        run_id=run_id, lease_owner="wrong_worker", extension_seconds=300, conn=conn
    )
    assert renewed_wrong_owner is False

    # Heartbeat renewal when expired should fail
    past_iso = (datetime.now(timezone(timedelta(hours=9))) - timedelta(seconds=10)).isoformat()
    conn.execute(
        "UPDATE hitl_runs SET lease_expires_at = ? WHERE run_id = ?", (past_iso, run_id)
    )
    conn.commit()

    renewed_expired = renew_lease_heartbeat(
        run_id=run_id, lease_owner=worker_id, extension_seconds=300, conn=conn
    )
    assert renewed_expired is False


def test_settle_run_outcome_conditions(test_memory_db_path):
    """Test conditional outcome settlement under healthy vs unhealthy worker and lease validity."""
    conn = get_db_connection()
    run_id = "run_settle_test"
    questions = [
        {"question_key": "q1", "question_type": "text", "display_text": "Q1", "is_required": 1}
    ]
    register_run_and_questions(
        run_id=run_id,
        handler="dummy_handler",
        checkpoint=None,
        question_set_id="set_1",
        questions_data=questions,
        title="Settle Test Run",
        display_type="test",
        conn=conn,
    )

    submit_answer(run_id, "set_1", "q1", answer="val", conn=conn)
    worker_id = "worker_settle"
    claim_run(run_id, worker_id, lease_duration_seconds=300, conn=conn)

    # Refuse settlement when worker is unhealthy
    settled_unhealthy = settle_run_outcome(
        run_id=run_id,
        lease_owner=worker_id,
        result_status="completed",
        is_worker_healthy=False,
        conn=conn,
    )
    assert settled_unhealthy is False

    # Successful settlement when healthy and lease valid
    settled_healthy = settle_run_outcome(
        run_id=run_id,
        lease_owner=worker_id,
        result_status="completed",
        checkpoint="cp_final",
        is_worker_healthy=True,
        conn=conn,
    )
    assert settled_healthy is True

    run = get_run(run_id, conn)
    assert run["status"] == "completed"
    assert run["checkpoint"] == "cp_final"
    assert run["lease_owner"] is None
    assert run["lease_expires_at"] is None


def test_main_cli_hitl_worker(monkeypatch):
    """Test main() CLI invocation with --hitl-worker propagates worker exit code."""
    called = {}

    def mock_run_hitl_worker_cli():
        called["run"] = True
        return 0

    monkeypatch.setattr("obsidian_ai_hub.hitl.worker.run_hitl_worker_cli", mock_run_hitl_worker_cli)
    monkeypatch.setattr("sys.argv", ["obsidian_ai_hub", "--hitl-worker"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert called.get("run") is True


def test_hitl_worker_loop_driven_run(test_memory_db_path):
    """Test driving run_loop for an active ready_to_resume run."""
    conn = get_db_connection()
    run_id = "run_loop_driven"

    def dummy_h(ctx: HitlContext) -> HitlResult:
        return HitlResult.complete("cp_loop_done")

    register_handler("dummy_h", dummy_h)

    questions = [
        {"question_key": "q1", "question_type": "text", "display_text": "Q1", "is_required": 1}
    ]
    register_run_and_questions(
        run_id=run_id,
        handler="dummy_h",
        checkpoint=None,
        question_set_id="set_1",
        questions_data=questions,
        title="Loop Driven",
        display_type="test",
        conn=conn,
    )

    submit_answer(run_id, "set_1", "q1", answer="loop_ans", conn=conn)

    worker = HitlWorker(worker_id="loop_worker", poll_interval=0.05)

    # Set draining to True after 0.2s in background thread so run_loop completes bounded execution
    def _drain_later():
        time.sleep(0.2)
        worker.draining = True

    t = threading.Thread(target=_drain_later, daemon=True)
    t.start()

    code = worker.run_loop(conn=conn)
    assert code == 0

    run = get_run(run_id, conn)
    assert run["status"] == "completed"
    assert run["checkpoint"] == "cp_loop_done"
