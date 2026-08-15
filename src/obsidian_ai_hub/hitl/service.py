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
    title: Optional[str] = None,
    description: Optional[str] = None,
    display_type: Optional[str] = None,
) -> None:
    """
    Register or update a Run and insert or update its active question set of questions.
    Ensures all operations occur within a single transaction and are completely idempotent.
    """
    # Pre-validate expires_at ISO 8601 format on all questions before opening transaction
    for q_data in questions_data:
        expires_at = q_data.get("expires_at")
        if expires_at is not None:
            if not isinstance(expires_at, str):
                raise ValueError("expires_at must be an ISO 8601 datetime string")
            try:
                dt = datetime.fromisoformat(expires_at)
                # Ensure UTC offset (timezone aware) is required
                if dt.tzinfo is None:
                    raise ValueError("expires_at must be a timezone-aware datetime with a UTC offset")
            except ValueError as e:
                raise ValueError(f"Invalid ISO 8601 datetime format for expires_at '{expires_at}': {e}") from e

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        with conn:
            # Check if run exists
            run = get_run(run_id, conn)
            now = get_current_iso()

            # Metadata Validation & Contract checks
            if run is None:
                # New Run: display_type and title are absolutely required, including non-blank constraint
                if not display_type or not display_type.strip():
                    raise ValueError("display_type is required for registering a new HITL Run")
                if not title or not title.strip():
                    raise ValueError("title is required for registering a new HITL Run")

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
                    "title": title.strip(),
                    "description": description.strip() if description and description.strip() else None,
                    "display_type": display_type.strip(),
                }
            else:
                # Existing Run update:
                # - If display_type/title is not None but blank, raise ValueError (prevent wiping metadata)
                # - If None, keep the existing value
                if display_type is not None:
                    if not display_type.strip():
                        raise ValueError("display_type cannot be set to empty/blank string on existing HITL Run")
                    run["display_type"] = display_type.strip()

                if title is not None:
                    if not title.strip():
                        raise ValueError("title cannot be set to empty/blank string on existing HITL Run")
                    run["title"] = title.strip()

                if description is not None:
                    run["description"] = description.strip() if description.strip() else None

                run["handler"] = handler
                run["checkpoint"] = checkpoint
                run["active_question_set_id"] = question_set_id
                run["status"] = "pending_user"
                run["lease_owner"] = None
                run["lease_expires_at"] = None
                run["updated_at"] = now

            # Validate structural choices for questions to avoid mixing scalar and structured types
            for q_data in questions_data:
                choices = q_data.get("choices")
                if choices:
                    if not isinstance(choices, list):
                        raise ValueError("choices must be a list if provided")

                    is_structured = [isinstance(c, dict) for c in choices]
                    if any(is_structured) and not all(is_structured):
                        raise ValueError("Cannot mix structured choices (dictionaries) and scalar choices in the same question")

                    if all(is_structured):
                        # Structured Choice array constraints:
                        # - value is JSON scalar (str, int, float, bool)
                        # - label is non-blank string
                        # - description is optional string
                        # - No duplicate values allowed
                        seen_values = set()
                        for c in choices:
                            val = c.get("value")
                            label = c.get("label")
                            desc = c.get("description")

                            if val is None:
                                raise ValueError("Each structured choice must have a 'value'")
                            if not isinstance(val, (str, int, float, bool)):
                                raise ValueError("Choice value must be a scalar JSON type (string, number, or boolean)")

                            if not label or not isinstance(label, str) or not label.strip():
                                raise ValueError("Each structured choice must have a non-empty string 'label'")

                            if desc is not None and not isinstance(desc, str):
                                raise ValueError("Structured choice description must be a string if provided")

                            if val in seen_values:
                                raise ValueError(f"Duplicate choice value detected: {val}")
                            seen_values.add(val)

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
                        "context_json": q_data.get("context_json"),
                    })
                    sql = """
                        UPDATE hitl_questions
                        SET question_type = ?, display_text = ?, choices = ?,
                            is_required = ?, expires_at = ?, updated_at = ?,
                            sequence = ?, title = ?, prompt = ?, context_json = ?
                        WHERE question_id = ?
                    """
                    conn.execute(sql, (
                        q_data["question_type"],
                        q_data["display_text"],
                        db_updates["choices"],
                        q_data.get("is_required", 1),
                        q_data.get("expires_at"),
                        now,
                        q_data.get("sequence", 0),
                        q_data.get("title"),
                        q_data.get("prompt"),
                        db_updates["context_json"],
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
                        "sequence": q_data.get("sequence", 0),
                        "title": q_data.get("title"),
                        "prompt": q_data.get("prompt"),
                        "context_json": q_data.get("context_json"),
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


def renew_lease_heartbeat(
    run_id: str,
    lease_owner: str,
    extension_seconds: int = 300,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """
    Extend the lease of an actively running run if ownership and validity conditions are met.
    Condition: status == 'running' AND lease_owner == lease_owner AND lease_expires_at >= now.
    Updates lease_expires_at to (now + extension_seconds).
    Returns True if update succeeded, False if condition failed.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        with conn:
            now = get_current_iso()
            expires_dt = datetime.now(timezone(timedelta(hours=9))) + timedelta(
                seconds=extension_seconds
            )
            new_lease_expires_at = expires_dt.isoformat()

            sql = """
                UPDATE hitl_runs
                SET lease_expires_at = ?,
                    updated_at = ?
                WHERE run_id = ? AND
                      status = 'running' AND
                      lease_owner = ? AND
                      lease_expires_at IS NOT NULL AND
                      lease_expires_at >= ?
            """
            cursor = conn.cursor()
            cursor.execute(sql, (new_lease_expires_at, now, run_id, lease_owner, now))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Heartbeat failed with exception for run {run_id}: {e}")
        return False
    finally:
        if close_conn:
            conn.close()


def settle_run_outcome(
    run_id: str,
    lease_owner: str,
    result_status: str,
    checkpoint: Optional[str] = None,
    error_message: Optional[str] = None,
    is_worker_healthy: bool = True,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """
    Conditionally update the final result of a run execution.
    Target statuses: 'completed', 'failed', 're_suspended'.
    Requires is_worker_healthy to be True AND:
      status == 'running' AND lease_owner == lease_owner AND lease_expires_at >= now
    (Or for re_suspended if handler already set status != 'running' and cleared lease).
    Returns True if outcome was committed, False if rejected/unhealthy.
    """
    if not is_worker_healthy:
        logger.error(f"Worker is unhealthy; refusing to settle run outcome for {run_id}.")
        return False

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        with conn:
            now = get_current_iso()
            run = get_run(run_id, conn)
            if run is None:
                logger.error(f"Run {run_id} not found during settlement.")
                return False

            # Handle case where handler already re-suspended and cleared lease
            if result_status == "re_suspended" and run["status"] != "running":
                logger.info(f"Run {run_id} was already re-suspended inside handler.")
                return True

            # Determine new status based on result_status
            if result_status == "completed":
                new_status = "completed"
                new_err = None
            elif result_status == "failed":
                new_status = "failed"
                new_err = error_message
            elif result_status == "re_suspended":
                new_status = "pending_user"
                new_err = None
            else:
                logger.error(f"Invalid result status '{result_status}' for run {run_id}")
                return False

            new_checkpoint = checkpoint or run["checkpoint"]

            sql = """
                UPDATE hitl_runs
                SET status = ?,
                    checkpoint = ?,
                    error_message = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE run_id = ? AND
                      status = 'running' AND
                      lease_owner = ? AND
                      lease_expires_at IS NOT NULL AND
                      lease_expires_at >= ?
            """
            cursor = conn.cursor()
            cursor.execute(
                sql,
                (new_status, new_checkpoint, new_err, now, run_id, lease_owner, now),
            )
            if cursor.rowcount == 0:
                logger.error(
                    f"Settlement conditional update failed for run {run_id} (lease expired or lost)."
                )
                return False

            logger.info(f"Successfully settled run {run_id} with status {new_status}")
            return True
    except Exception as e:
        logger.exception(f"Exception during settlement of run {run_id}: {e}")
        return False
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

            # Normalize answer to {value, comment} format
            if not isinstance(answer, dict):
                answer = {"value": answer, "comment": None}
            answer_value = answer.get("value")

            # Check comment requirement for memory maintenance feedback
            maint_ctx = question.get("context_json")
            if maint_ctx and isinstance(maint_ctx, dict) and maint_ctx.get("type") == "memory_maintenance":
                if answer_value == "feedback":
                    comment = answer.get("comment")
                    if not comment or not comment.strip():
                        raise ValueError("フィードバックして再提案を選択した場合は、コメントを入力してください。")

            # Validate answer value against choices if specified
            choices = question.get("choices")
            if choices is not None:
                if isinstance(choices, list) and len(choices) > 0:
                    is_structured = [isinstance(c, dict) for c in choices]
                    if all(is_structured):
                        valid_values = [c["value"] for c in choices]
                        if answer_value not in valid_values:
                            raise ValueError(
                                f"Answer '{answer_value}' is not a valid choice value. Valid choice values: {valid_values}"
                            )
                    else:
                        if answer_value not in choices:
                            raise ValueError(
                                f"Answer '{answer_value}' is not a valid choice. Valid choices: {choices}"
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
