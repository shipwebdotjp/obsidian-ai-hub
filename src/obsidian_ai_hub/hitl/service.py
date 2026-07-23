from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl.store import (
    get_run,
    upsert_run,
    insert_question,
    get_question,
    get_questions_by_set,
    update_question_status_and_answer,
    update_pending_question_answer,
    bulk_update_questions_status_by_set,
    generate_question_id,
    serialize_question,
)

logger = logging.getLogger(__name__)


def get_current_iso() -> str:
    """Get the current JST time in ISO-8601 format."""
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).isoformat()


def register_run_and_questions(
    run_id: str,
    handler: str,
    checkpoint: Optional[str],
    question_set_id: str,
    questions_data: List[Dict[str, Any]],
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """
    Register or update a Run and insert or update its active question set of questions.
    Ensures all operations occur within a single transaction and are completely idempotent.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        with conn:
            # Check if run exists
            run = get_run(run_id, conn)
            now = get_current_iso()

            if run is None:
                run = {
                    "run_id": run_id,
                    "handler": handler,
                    "status": "pending_user",
                    "checkpoint": checkpoint,
                    "active_question_set_id": question_set_id,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "retry_count": 0,
                    "error_message": None,
                    "created_at": now,
                    "updated_at": now,
                }
            else:
                run["handler"] = handler
                run["checkpoint"] = checkpoint
                run["active_question_set_id"] = question_set_id
                run["status"] = "pending_user"
                run["lease_owner"] = None
                run["lease_expires_at"] = None
                run["updated_at"] = now

            # Upsert the run first to satisfy foreign key constraint on questions
            upsert_run(run, conn)

            # Insert or update questions
            for q_data in questions_data:
                existing_q = get_question(run_id, question_set_id, q_data["question_key"], conn)
                if existing_q is not None:
                    # Update while preserving question_id, status, and answer
                    q_id = existing_q["question_id"]
                    db_updates = serialize_question({
                        "choices": q_data.get("choices"),
                    })
                    sql = """
                        UPDATE hitl_questions
                        SET question_type = ?, display_text = ?, choices = ?, is_required = ?, expires_at = ?, updated_at = ?
                        WHERE question_id = ?
                    """
                    conn.execute(sql, (
                        q_data["question_type"],
                        q_data["display_text"],
                        db_updates["choices"],
                        q_data.get("is_required", 1),
                        q_data.get("expires_at"),
                        now,
                        q_id
                    ))
                else:
                    q = {
                        "question_id": generate_question_id(),
                        "run_id": run_id,
                        "question_set_id": question_set_id,
                        "question_key": q_data["question_key"],
                        "status": "pending",
                        "question_type": q_data["question_type"],
                        "display_text": q_data["display_text"],
                        "choices": q_data.get("choices"),
                        "answer": None,
                        "is_required": q_data.get("is_required", 1),
                        "expires_at": q_data.get("expires_at"),
                        "answered_at": None,
                        "created_at": now,
                        "updated_at": now,
                    }
                    insert_question(q, conn)

            # Re-evaluate run status based on actual active set's questions in database
            all_questions = get_questions_by_set(run_id, question_set_id, conn)
            pending_required = [
                q for q in all_questions
                if q["is_required"] == 1 and q["status"] == "pending"
            ]
            if len(pending_required) == 0:
                run["status"] = "ready_to_resume"
            else:
                run["status"] = "pending_user"

            upsert_run(run, conn)
    except sqlite3.IntegrityError as e:
        logger.error(f"Database integrity violation in register_run_and_questions: {e}")
        raise
    finally:
        if close_conn:
            conn.close()


def submit_answer(
    run_id: str,
    question_set_id: str,
    question_key: str,
    answer: Any,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """
    Save the answer for a specific question.
    Ensures once-only answer rule and choices verification.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        with conn:
            # Get Question
            question = get_question(run_id, question_set_id, question_key, conn)
            if question is None:
                raise ValueError(
                    f"Question not found: run_id={run_id}, set={question_set_id}, key={question_key}"
                )

            # Get Run
            run = get_run(run_id, conn)
            if run is None:
                raise ValueError(f"Run {run_id} not found")

            # Validate that the supplied question_set_id is currently active
            if run["active_question_set_id"] != question_set_id:
                raise ValueError(
                    f"Cannot submit answer for inactive or historical question set: {question_set_id}. "
                    f"Active set is {run['active_question_set_id']}"
                )

            # Check once-only answer constraint
            if question["status"] != "pending":
                raise ValueError(
                    f"Question {question_key} is already finalized (status: {question['status']})"
                )

            # Validate answer against choices if specified
            choices = question.get("choices")
            if choices is not None:
                if isinstance(choices, list) and len(choices) > 0:
                    if answer not in choices:
                        raise ValueError(
                            f"Answer '{answer}' is not a valid choice. Valid choices: {choices}"
                        )

            # Update question conditionally only if it is still pending
            now = get_current_iso()
            success = update_pending_question_answer(
                question["question_id"],
                answer=answer,
                answered_at=now,
                conn=conn,
            )
            if not success:
                raise ValueError(
                    f"Conflict detected: Question {question_key} has already been answered, skipped, or cancelled by another transaction."
                )

            # Check if all required questions in active set of the run are answered
            active_set_id = run["active_question_set_id"]
            if active_set_id:
                all_questions = get_questions_by_set(run_id, active_set_id, conn)
                pending_required = [
                    q for q in all_questions
                    if q["is_required"] == 1 and q["status"] == "pending"
                ]

                if len(pending_required) == 0:
                    run["status"] = "ready_to_resume"
                else:
                    run["status"] = "pending_user"

                run["updated_at"] = now
                upsert_run(run, conn)
    finally:
        if close_conn:
            conn.close()


def cancel_run(
    run_id: str,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """
    Cancel a run and mark all of its pending active questions as cancelled.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        with conn:
            run = get_run(run_id, conn)
            if run is None:
                raise ValueError(f"Run {run_id} not found")

            now = get_current_iso()
            run["status"] = "cancelled"
            run["updated_at"] = now
            upsert_run(run, conn)

            active_set_id = run.get("active_question_set_id")
            if active_set_id:
                bulk_update_questions_status_by_set(
                    run_id, active_set_id, from_status="pending", to_status="cancelled", conn=conn
                )
    finally:
        if close_conn:
            conn.close()


def claim_run(
    run_id: str,
    lease_owner: str,
    lease_duration_seconds: int,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """
    Acquire an atomic lease/claim on a run.
    Sets optional unanswered questions to 'skipped' status.
    Ensures safe conditional write under WAL to prevent stale run state reads.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        with conn:
            run = get_run(run_id, conn)
            if run is None:
                raise ValueError(f"Run {run_id} not found")

            now = get_current_iso()
            expires_dt = datetime.now(timezone(timedelta(hours=9))) + timedelta(
                seconds=lease_duration_seconds
            )
            lease_expires_at = expires_dt.isoformat()

            # Atomic conditional update using lexicographically sortable ISO dates.
            # Allows reclaiming if run is ready_to_resume, or if running but lease_expires_at is in the past.
            sql = """
                UPDATE hitl_runs
                SET status = 'running',
                    lease_owner = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE run_id = ? AND (
                    status = 'ready_to_resume' OR (
                        status = 'running' AND
                        lease_expires_at IS NOT NULL AND
                        lease_expires_at < ?
                    )
                )
            """
            cursor = conn.cursor()
            cursor.execute(sql, (lease_owner, lease_expires_at, now, run_id, now))

            if cursor.rowcount == 0:
                # Reclaimability check failed atomically
                return False

            # The update succeeded! Apply optional-question skipping
            active_set_id = run["active_question_set_id"]
            if active_set_id:
                questions = get_questions_by_set(run_id, active_set_id, conn)
                for q in questions:
                    if q["is_required"] == 0 and q["status"] == "pending":
                        update_question_status_and_answer(
                            q["question_id"],
                            status="skipped",
                            answer=None,
                            answered_at=now,
                            conn=conn,
                        )

            return True
    finally:
        if close_conn:
            conn.close()


def update_checkpoint(
    run_id: str,
    checkpoint: str,
    error_message: Optional[str] = None,
    retry_count_delta: int = 0,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """
    Update checkpoint, error message and retry count for a run.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        with conn:
            run = get_run(run_id, conn)
            if run is None:
                raise ValueError(f"Run {run_id} not found")

            now = get_current_iso()
            run["checkpoint"] = checkpoint
            if error_message is not None:
                run["error_message"] = error_message
            run["retry_count"] += retry_count_delta
            run["updated_at"] = now

            upsert_run(run, conn)
    finally:
        if close_conn:
            conn.close()
