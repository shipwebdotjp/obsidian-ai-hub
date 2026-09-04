from __future__ import annotations

import logging
import signal
import sqlite3
import sys
import threading
import time
import uuid
from typing import Any, Dict, Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl.dispatcher import (
    HitlContext,
    HitlResult,
    get_eligible_runs,
    get_handler,
    list_handler_names,
    process_expired_questions,
)
from obsidian_ai_hub.hitl.service import (
    claim_run,
    renew_lease_heartbeat,
    settle_run_outcome,
)
from obsidian_ai_hub.hitl.store import (
    get_questions_by_set,
    get_run,
)

logger = logging.getLogger(__name__)


class HeartbeatRunner:
    """Runs a background thread to renew lease every interval seconds using a dedicated DB connection."""

    def __init__(
        self,
        run_id: str,
        worker_id: str,
        interval: float = 60.0,
        extension_seconds: int = 300,
    ) -> None:
        self.run_id = run_id
        self.worker_id = worker_id
        self.interval = interval
        self.extension_seconds = extension_seconds
        self.stop_event = threading.Event()
        self.is_healthy = True
        self.thread: Optional[threading.Thread] = None

    def _loop(self) -> None:
        while not self.stop_event.wait(timeout=self.interval):
            try:
                # Use a dedicated connection inside thread to avoid sharing connections
                success = renew_lease_heartbeat(
                    self.run_id,
                    self.worker_id,
                    extension_seconds=self.extension_seconds,
                )
                if not success:
                    logger.error(
                        f"Heartbeat renewal failed for run {self.run_id} under worker {self.worker_id}."
                    )
                    self.is_healthy = False
                    break
            except Exception as e:
                logger.exception(
                    f"Unexpected exception during heartbeat renewal for run {self.run_id}: {e}"
                )
                self.is_healthy = False
                break

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)


class HitlWorker:
    """Resident worker that claims ready_to_resume HITL runs and executes them sequentially with lease heartbeats."""

    def __init__(
        self,
        worker_id: Optional[str] = None,
        poll_interval: float = 5.0,
        lease_duration: int = 300,
        heartbeat_interval: float = 60.0,
    ) -> None:
        self.worker_id = worker_id or f"hitl_worker_{uuid.uuid4().hex}"
        self.poll_interval = poll_interval
        self.lease_duration = lease_duration
        self.heartbeat_interval = heartbeat_interval
        self.draining = False
        self.is_healthy = True

    def setup_signal_handlers(self) -> None:
        """Register SIGTERM and SIGINT signal handlers for graceful draining."""

        def _handle_signal(signum: int, frame: Any) -> None:
            sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
            logger.info(f"Received {sig_name}. Transitioning HITL worker {self.worker_id} to draining mode.")
            self.draining = True

        try:
            signal.signal(signal.SIGTERM, _handle_signal)
            signal.signal(signal.SIGINT, _handle_signal)
        except (ValueError, OSError):
            # Signal handling may fail if not in main thread (e.g. in tests)
            pass

    def execute_run(self, run_record: Dict[str, Any], conn: sqlite3.Connection) -> bool:
        """
        Claim, execute handler with heartbeat, and settle outcome for a single Run.
        Returns True if execution and settlement succeeded.
        """
        run_id = run_record["run_id"]
        handler_name = run_record["handler"]

        # 1. Claim run
        try:
            claimed = claim_run(run_id, self.worker_id, self.lease_duration, conn)
        except Exception as e:
            logger.exception(f"Failed to claim run {run_id}: {e}")
            return False

        if not claimed:
            logger.info(f"Could not claim run {run_id}, skipping.")
            return False

        logger.info(f"Successfully claimed run {run_id} with worker {self.worker_id}")

        # 2. Check handler registration
        handler = get_handler(handler_name)
        if not handler:
            err_msg = (
                f"Handler '{handler_name}' is not registered. "
                f"Registered: {list_handler_names() or '(none)'} "
                "(restart the worker if handlers were added after it started)."
            )
            logger.error(err_msg)
            settled = settle_run_outcome(
                run_id=run_id,
                lease_owner=self.worker_id,
                result_status="failed",
                error_message=err_msg,
                is_worker_healthy=self.is_healthy,
                conn=conn,
            )
            return settled

        # 3. Setup context
        active_set_id = run_record["active_question_set_id"]
        questions = get_questions_by_set(run_id, active_set_id, conn) if active_set_id else []
        answers = {}
        raw_answers = {}
        for q in questions:
            ans = q["answer"]
            raw_answers[q["question_key"]] = ans
            if isinstance(ans, dict):
                answers[q["question_key"]] = ans.get("value", ans)
            else:
                answers[q["question_key"]] = ans

        context = HitlContext(
            run_id=run_id,
            checkpoint=run_record["checkpoint"],
            answers_by_question_key=answers,
            conn=conn,
            raw_answers_by_question_key=raw_answers,
        )

        # 4. Start heartbeat thread
        heartbeat = HeartbeatRunner(
            run_id=run_id,
            worker_id=self.worker_id,
            interval=self.heartbeat_interval,
            extension_seconds=self.lease_duration,
        )
        heartbeat.start()

        # 5. Execute handler
        try:
            try:
                result = handler(context)
                if not isinstance(result, HitlResult):
                    result = HitlResult.fail(
                        f"Handler must return a HitlResult, got {type(result)}"
                    )
            except Exception as e:
                logger.exception(f"Error executing handler '{handler_name}' for run {run_id}")
                result = HitlResult.fail(f"Handler execution failed: {str(e)}")

            # Check heartbeat thread health
            if not heartbeat.is_healthy:
                logger.error(
                    f"Heartbeat thread reported failure for run {run_id}. Worker is unhealthy."
                )
                self.is_healthy = False

            # Stop heartbeat thread
            heartbeat.stop()

            # 6. Settle outcome conditionally
            settled = settle_run_outcome(
                run_id=run_id,
                lease_owner=self.worker_id,
                result_status=result.status,
                checkpoint=result.checkpoint,
                error_message=result.error_message,
                is_worker_healthy=self.is_healthy,
                conn=conn,
            )

            if not settled or not self.is_healthy:
                logger.error(
                    f"Settlement failed or worker unhealthy for run {run_id}. Marking worker unhealthy."
                )
                self.is_healthy = False
                return False

            return True

        finally:
            heartbeat.stop()

    def run_loop(self, conn: Optional[sqlite3.Connection] = None) -> int:
        """
        Main worker loop. Runs until drained or unhealthy.
        Returns 0 on normal drain / exit, or 1 on unhealthy termination.
        """
        self.setup_signal_handlers()
        logger.info(f"Starting HITL worker loop ({self.worker_id})")
        logger.info(f"Registered HITL handlers: {list_handler_names() or '(none)'})")

        close_conn = False
        if conn is None:
            conn = get_db_connection()
            close_conn = True

        processed_total = 0

        try:
            while True:
                if self.draining:
                    logger.info("Worker is draining. Exiting loop.")
                    return 0

                # 1. Process expired questions
                try:
                    process_expired_questions(conn)
                except Exception as e:
                    logger.exception(f"Error processing expired questions: {e}")

                # 2. Get eligible runs
                eligible_runs = get_eligible_runs(conn)

                if eligible_runs:
                    for run_record in eligible_runs:
                        if self.draining:
                            logger.info("Worker is draining. Stopping before starting next run.")
                            return 0

                        success = self.execute_run(run_record, conn)
                        if success:
                            processed_total += 1
                        elif not self.is_healthy:
                            logger.error("Worker became unhealthy during run execution. Exiting with status 1.")
                            return 1

                # 3. Wait for poll interval or signal
                sleep_start = time.time()
                while time.time() - sleep_start < self.poll_interval:
                    if self.draining:
                        logger.info("Worker received drain signal during sleep. Exiting.")
                        return 0
                    time.sleep(0.1)

        finally:
            if close_conn:
                conn.close()


def run_hitl_worker_cli() -> int:
    """CLI entrypoint for python -m obsidian_ai_hub --hitl-worker."""
    worker = HitlWorker()
    return worker.run_loop()
