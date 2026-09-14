"""Shared child-run waiting loop for Task adapters."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.execution import TaskCancelled

logger = logging.getLogger(__name__)


def wait_for_child_run(
    task_id: str,
    get_run: Callable[[], Optional[dict[str, Any]]],
    request_cancel: Callable[[], None],
    terminal_statuses: frozenset[str],
    poll_interval: float = 2.0,
    timeout_secs: float = 1800.0,
) -> dict[str, Any]:
    """Poll a child run until terminal.

    When the task enters ``cancelling``, the child cancel is requested and
    ``TaskCancelled`` is raised once the child reaches a terminal status.
    A stuck non-terminal child fails the step after ``timeout_secs`` so the
    serial task worker is never blocked indefinitely.
    """
    cancel_requested = False
    deadline = time.monotonic() + timeout_secs
    while True:
        run = get_run()
        if run is None:
            raise ValueError("Child run disappeared while waiting.")
        status = str(run.get("status"))
        if status in terminal_statuses:
            if cancel_requested:
                raise TaskCancelled(f"Task '{task_id}' was cancelled.")
            return run
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Child run for task '{task_id}' did not finish "
                f"within {timeout_secs} seconds."
            )
        if not cancel_requested and _task_is_cancelling(task_id):
            logger.info("Task %s cancelling; requesting child cancel", task_id)
            request_cancel()
            cancel_requested = True
        time.sleep(poll_interval)


def _task_is_cancelling(task_id: str) -> bool:
    task = task_store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task '{task_id}' disappeared while waiting.")
    return str(task["status"]) == "cancelling"
