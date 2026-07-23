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
    bulk_update_questions_status_by_set,
    generate_question_id,
    get_current_iso,
)

logger = logging.getLogger(__name__)


def register_run_and_questions(
    run_id: str,
    handler: str,
    checkpoint: Optional[str],
    question_set_id: str,
    questions_data: List[Dict[str, Any]],
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """
    Register or update a Run and insert its active question set of questions.
    Ensures all operations occur within a single transaction.
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

            # Check if there are any required pending questions in this newly registered set
            required_pending = [q for q in questions_data if q.get("is_required", 1) == 1]
            if len(required_pending) == 0:
                run["status"] = "ready_to_resume"

            # Upsert the run first to satisfy foreign key constraint on questions
            upsert_run(run, conn)

            # Insert questions
            for q_data in questions_data:
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

            # Update question
            now = get_current_iso()
            update_question_status_and_answer(
                question["question_id"],
                status="answered",
                answer=answer,
                answered_at=now,
                conn=conn,
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
            is_reclaimable = False

            if run["status"] == "ready_to_resume":
                is_reclaimable = True
            elif run["status"] == "running" and run.get("lease_expires_at"):
                try:
                    expires = datetime.fromisoformat(run["lease_expires_at"])
                    if expires.tzinfo is None:
                        jst = timezone(timedelta(hours=9))
                        expires = expires.replace(tzinfo=jst)
                    now_dt = datetime.now(timezone(timedelta(hours=9)))
                    if now_dt > expires:
                        is_reclaimable = True
                except Exception as e:
                    logger.warning(f"Error parsing lease_expires_at for run {run_id}: {e}")
                    pass

            if not is_reclaimable:
                return False

            # Mark unanswered optional questions as skipped
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

            # Update run lease
            expires_dt = datetime.now(timezone(timedelta(hours=9))) + timedelta(
                seconds=lease_duration_seconds
            )
            run["status"] = "running"
            run["lease_owner"] = lease_owner
            run["lease_expires_at"] = expires_dt.isoformat()
            run["updated_at"] = now
            upsert_run(run, conn)
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
