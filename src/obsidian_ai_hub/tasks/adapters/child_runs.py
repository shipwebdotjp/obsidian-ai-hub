"""Shared child-run waiting loop for Task adapters."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Optional

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.execution import (
    CANCEL_CERTAINTY_CANCELLED,
    CANCEL_CERTAINTY_COMPLETED,
    CANCEL_CERTAINTY_UNKNOWN,
    CancellationEvidence,
    TaskCancelled,
)

logger = logging.getLogger(__name__)


def classify_cancel_certainty(status: Any) -> str:
    """Map a child run's terminal status to cancellation certainty.

    ``cancel``/``cancelled`` means cooperative cancellation was confirmed;
    ``succeeded``/``completed`` means the process finished before the request
    could stop it; anything else (failed, interrupted, unknown) is uncertain.
    """
    normalized = str(status or "").lower()
    if normalized in ("cancel", "cancelled", "canceled"):
        return CANCEL_CERTAINTY_CANCELLED
    if normalized in ("succeeded", "completed", "success"):
        return CANCEL_CERTAINTY_COMPLETED
    return CANCEL_CERTAINTY_UNKNOWN

TASK_SESSION_TITLE_LIMIT = 30
"""Max chars for a Task-created child session title (matches the agents title convention)."""

_LEGACY_TASK_SESSION_TITLE_PATTERN = re.compile(r"^Task \S+ step \d+$")


def is_task_generated_session_title(title: Any) -> bool:
    """Return True for the legacy ``Task <id> step <n>`` session titles.

    These titles carry no work description, so backends may refine them via
    their formal auto-title paths. User-supplied and content-derived titles
    never match and stay protected.
    """
    if not isinstance(title, str):
        return False
    return bool(_LEGACY_TASK_SESSION_TITLE_PATTERN.match(title.strip()))


def build_task_session_title(
    task_id: str,
    step_index: int,
    step: dict[str, Any],
    plan: dict[str, Any] | None = None,
    limit: int = TASK_SESSION_TITLE_LIMIT,
) -> str:
    """Build a short content-aware title for a Task-created child session.

    Preference order: the step's work hint (``inputs.task``), the step's own
    title (legacy static steps, or the orchestrator's rationale), the plan
    purpose, and finally the legacy ``Task <id> step <n>`` pattern as a
    last resort for empty content.
    """
    candidates: list[str] = []
    inputs = step.get("inputs")
    if isinstance(inputs, dict):
        candidates.append(str(inputs.get("task") or ""))
    candidates.append(str(step.get("title") or ""))
    plan_inner = (plan or {}).get("plan", {}) if isinstance(plan, dict) else {}
    if isinstance(plan_inner, dict):
        candidates.append(str(plan_inner.get("purpose") or ""))
    capability_key = str(step.get("capability_key") or "")
    for candidate in candidates:
        cleaned = re.sub(r"\s+", " ", candidate.strip()).strip()
        if not cleaned or cleaned == capability_key:
            continue
        if len(cleaned) > limit:
            cleaned = cleaned[:limit].rstrip()
        if cleaned:
            return cleaned
    return f"Task {task_id} step {step_index}"


def find_prior_child_session(
    task_id: str,
    child_kind: str,
    target_match: Callable[[dict[str, Any]], bool],
    resolve_session_id: Callable[[str], Optional[str]],
) -> Optional[str]:
    """Return the most recent reusable child session for this task, if any.

    Scans the task's own ``child_run_started`` events (newest first) for a
    run whose target matches ``target_match``. ``resolve_session_id`` maps an
    old ``child_run_id`` to its session when the event predates session
    recording. Events from other tasks are never consulted.
    """
    try:
        events = task_store.list_task_events(task_id)
    except Exception:
        logger.warning("Task %s events unreadable; starting a new session", task_id)
        return None
    for event in reversed(events):
        if event.get("event_type") != "child_run_started":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if str(payload.get("child_kind")) != child_kind:
            continue
        try:
            if not target_match(payload):
                continue
        except Exception:
            continue
        session_id = payload.get("session_id")
        if not session_id:
            run_id = payload.get("child_run_id")
            if not run_id:
                continue
            try:
                session_id = resolve_session_id(str(run_id))
            except Exception:
                logger.warning(
                    "Task %s prior run '%s' session unresolvable; skipping",
                    task_id,
                    run_id,
                )
                continue
        if session_id:
            return str(session_id)
    return None


def wait_for_child_run(
    task_id: str,
    get_run: Callable[[], Optional[dict[str, Any]]],
    request_cancel: Callable[[], None],
    terminal_statuses: frozenset[str],
    poll_interval: float = 2.0,
    timeout_secs: float = 1800.0,
    waiting_statuses: frozenset[str] = frozenset(),
    on_first_wait: Optional[Callable[[dict[str, Any]], None]] = None,
    child_kind: Optional[str] = None,
    child_run_id: Optional[str] = None,
) -> dict[str, Any]:
    """Poll a child run until terminal.

    When the task enters ``cancelling``, the child cancel is requested and
    ``TaskCancelled`` is raised once the child reaches a terminal status.
    A stuck non-terminal child fails the step after ``timeout_secs`` so the
    serial task worker is never blocked indefinitely.

    Statuses in ``waiting_statuses`` (e.g. ``waiting_user`` while a child
    run waits for a HITL answer) are exempt from the timeout: the deadline
    is refreshed on every such poll so active execution after the answer
    still gets the full budget. ``on_first_wait`` fires once with the run
    dict when first entering a waiting status so callers can record the
    HITL linkage (task event with the HITL run id).
    """
    cancel_requested = False
    notified_waiting = False
    deadline = time.monotonic() + timeout_secs
    while True:
        run = get_run()
        if run is None:
            raise ValueError("Child run disappeared while waiting.")
        status = str(run.get("status"))
        if status in terminal_statuses:
            if cancel_requested:
                raise TaskCancelled(
                    f"Task '{task_id}' was cancelled.",
                    evidence=CancellationEvidence(
                        child_kind=child_kind,
                        child_run_id=child_run_id,
                        result_certainty=classify_cancel_certainty(status),
                    ),
                )
            return run
        in_waiting = status in waiting_statuses
        if in_waiting:
            deadline = time.monotonic() + timeout_secs
            if not notified_waiting:
                notified_waiting = True
                if on_first_wait is not None:
                    try:
                        on_first_wait(run)
                    except Exception:
                        logger.exception("Task %s waiting notification failed", task_id)
        elif time.monotonic() > deadline:
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
