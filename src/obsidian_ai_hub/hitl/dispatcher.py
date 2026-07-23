from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl.store import (
    auto_connection,
    get_current_iso,
    get_run,
    upsert_run,
    get_questions_by_set,
)
from obsidian_ai_hub.hitl.service import (
    claim_run,
    register_run_and_questions,
)

logger = logging.getLogger(__name__)


@dataclass
class HitlContext:
    run_id: str
    checkpoint: Optional[str]
    answers_by_question_key: Dict[str, Any]
    conn: sqlite3.Connection

    def register_next_questions(
        self,
        question_set_id: str,
        questions_data: List[Dict[str, Any]],
        checkpoint: Optional[str] = None,
    ) -> None:
        """Helper to register a subsequent question set within the same transaction."""
        run = get_run(self.run_id, self.conn)
        if run is None:
            raise RuntimeError(f"Run {self.run_id} not found when registering next questions")
        handler_name = run["handler"]
        register_run_and_questions(
            run_id=self.run_id,
            handler=handler_name,
            checkpoint=checkpoint or self.checkpoint,
            question_set_id=question_set_id,
            questions_data=questions_data,
            conn=self.conn,
        )


@dataclass
class HitlResult:
    status: str  # "completed", "failed", or "re_suspended"
    checkpoint: Optional[str] = None
    error_message: Optional[str] = None

    @classmethod
    def complete(cls, checkpoint: Optional[str] = None) -> HitlResult:
        return cls(status="completed", checkpoint=checkpoint)

    @classmethod
    def fail(cls, error_message: str, checkpoint: Optional[str] = None) -> HitlResult:
        return cls(status="failed", checkpoint=checkpoint, error_message=error_message)

    @classmethod
    def re_suspend(cls, checkpoint: Optional[str] = None) -> HitlResult:
        return cls(status="re_suspended", checkpoint=checkpoint)


# Handler Registry
_registry: Dict[str, Callable[[HitlContext], HitlResult]] = {}


def register_handler(name: str, handler: Callable[[HitlContext], HitlResult]) -> None:
    """Register a handler function under a name at the composition root."""
    _registry[name] = handler
    logger.info(f"Registered HITL handler: {name}")


def get_handler(name: str) -> Optional[Callable[[HitlContext], HitlResult]]:
    """Retrieve a registered handler."""
    return _registry.get(name)


def clear_handlers() -> None:
    """Clear all registered handlers (mainly for testing)."""
    _registry.clear()


def get_eligible_runs(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Fetch Runs ready to resume or running but with an expired lease."""
    sql = """
        SELECT * FROM hitl_runs
        WHERE status = 'ready_to_resume' OR (
            status = 'running' AND
            lease_expires_at IS NOT NULL AND
            lease_expires_at < ?
        )
    """
    now = get_current_iso()
    cursor = conn.cursor()
    cursor.execute(sql, (now,))
    return [dict(row) for row in cursor.fetchall()]


def _process_run(
    run_record: Dict[str, Any],
    worker_id: str,
    lease_duration: int,
    conn: sqlite3.Connection,
) -> bool:
    """
    Process a single eligible run by claiming, executing its handler,
    and committing outcome state in isolated transactions.
    """
    run_id = run_record["run_id"]
    handler_name = run_record["handler"]

    # Try to atomically claim the run
    claimed = claim_run(run_id, worker_id, lease_duration, conn)
    if not claimed:
        logger.info(f"Could not claim run {run_id}, skipping.")
        return False

    handler = get_handler(handler_name)
    if not handler:
        err_msg = f"Handler '{handler_name}' is not registered."
        logger.error(err_msg)
        with conn:
            now = get_current_iso()
            run = get_run(run_id, conn)
            if run:
                run["status"] = "failed"
                run["error_message"] = err_msg
                run["lease_owner"] = None
                run["lease_expires_at"] = None
                run["updated_at"] = now
                upsert_run(run, conn)
        return False

    active_set_id = run_record["active_question_set_id"]
    questions = get_questions_by_set(run_id, active_set_id, conn) if active_set_id else []
    answers = {q["question_key"]: q["answer"] for q in questions}

    context = HitlContext(
        run_id=run_id,
        checkpoint=run_record["checkpoint"],
        answers_by_question_key=answers,
        conn=conn,
    )

    try:
        with conn:
            result = handler(context)
            if not isinstance(result, HitlResult):
                raise ValueError(f"Handler must return a HitlResult, got {type(result)}")

            now = get_current_iso()
            run = get_run(run_id, conn)
            if run:
                # If re_suspended and the handler already registered next questions,
                # the run is already updated and the lease is already released.
                if result.status == "re_suspended" and run["status"] != "running":
                    logger.info(f"Run {run_id} was successfully re-suspended inside handler.")
                    return True

                if result.status == "completed":
                    run["status"] = "completed"
                    run["checkpoint"] = result.checkpoint or run["checkpoint"]
                    run["error_message"] = None
                elif result.status == "failed":
                    run["status"] = "failed"
                    run["checkpoint"] = result.checkpoint or run["checkpoint"]
                    run["error_message"] = result.error_message
                elif result.status == "re_suspended":
                    run["status"] = "pending_user"
                    run["checkpoint"] = result.checkpoint or run["checkpoint"]
                    run["error_message"] = None
                else:
                    raise ValueError(f"Invalid HitlResult status: {result.status}")

                # Release lease and persist state change
                run["lease_owner"] = None
                run["lease_expires_at"] = None
                run["updated_at"] = now
                upsert_run(run, conn)

        logger.info(f"Successfully processed run {run_id} with status {result.status}")
        return True

    except Exception as e:
        logger.exception(f"Error executing handler '{handler_name}' for run {run_id}")
        with conn:
            now = get_current_iso()
            run = get_run(run_id, conn)
            if run:
                run["status"] = "failed"
                run["error_message"] = f"Handler execution failed: {str(e)}"
                run["lease_owner"] = None
                run["lease_expires_at"] = None
                run["retry_count"] = run.get("retry_count", 0) + 1
                run["updated_at"] = now
                upsert_run(run, conn)
        return False


def dispatch_runs(conn: Optional[sqlite3.Connection] = None) -> int:
    """
    Atomically claims eligible runs and executes their handlers.
    Returns the number of successfully processed runs.
    """
    worker_id = f"dispatcher_{uuid.uuid4().hex}"
    lease_duration = 300  # 5 minutes

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    processed_count = 0
    try:
        eligible_runs = get_eligible_runs(conn)
        for run_record in eligible_runs:
            success = _process_run(run_record, worker_id, lease_duration, conn)
            if success:
                processed_count += 1
    finally:
        if close_conn:
            conn.close()

    return processed_count
