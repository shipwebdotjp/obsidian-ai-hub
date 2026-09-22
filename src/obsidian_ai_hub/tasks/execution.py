"""Plan step execution seam.

The worker runs saved plan steps through an injected ``StepExecutor``.
Each step's writes are independent atomic operations: adapters may poll
child runs for minutes, so no long-lived transaction spans the step loop.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from obsidian_ai_hub.tasks import store as task_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepResult:
    """Outcome of a single executed step.

    ``summary`` is the display/audit observation. ``observation_summary`` is
    an optional history gist; when omitted the orchestrator derives one from
    ``summary`` with the capability's two-layer budget
    (``tasks/observation.py``).
    """

    step_index: int
    capability_key: str
    summary: str
    observation_summary: Optional[str] = None
    child_kind: Optional[str] = None
    child_run_id: Optional[str] = None
    # Machine-checkable postconditions this step actually satisfied. The
    # adapter reports them so the Runtime Orchestrator can decide completion
    # from state instead of relying on the LLM's ``finish``.
    satisfied_effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutorOutcome:
    """Outcome of a whole-plan execution."""

    kind: str  # "completed" | "incomplete" | "failed" | "deviation"
    result_summary: Optional[str] = None
    error_summary: Optional[str] = None
    revised_plan: Optional[dict[str, Any]] = None
    deviation_reason: Optional[str] = None


class DeviationReported(Exception):
    """Raised by an executor to self-report a need outside the saved plan."""

    def __init__(self, revised_plan: dict[str, Any], reason: str) -> None:
        super().__init__(reason)
        self.revised_plan = revised_plan
        self.reason = reason


CANCEL_CERTAINTY_CANCELLED = "cancelled"
CANCEL_CERTAINTY_COMPLETED = "completed"
CANCEL_CERTAINTY_UNKNOWN = "unknown"


@dataclass(frozen=True)
class CancellationEvidence:
    """What is known about a child process when cancellation stopped waiting.

    Cancellation is a request, not a rollback: the child may have reached
    ``cancelled`` (cooperative), may have already ``completed`` before the
    request arrived, or may have ended in a state whose external effects are
    unknown. Callers use ``result_certainty`` to decide whether they can stop
    cleanly or must ask a human.
    """

    child_kind: Optional[str] = None
    child_run_id: Optional[str] = None
    result_certainty: str = CANCEL_CERTAINTY_UNKNOWN
    # Best-effort human-readable result recovered when the child actually
    # finished; lets the Workflow persist adoptable evidence instead of
    # discarding a completed external result.
    result_summary: Optional[str] = None


class TaskCancelled(Exception):
    """Raised by an adapter when the task entered ``cancelling`` mid-step.

    Carries the minimal :class:`CancellationEvidence` (child kind/id and how
    certain the outcome is) so an orchestrator can choose ``cancelled`` versus
    ``needs_attention`` instead of guessing.
    """

    def __init__(
        self, message: str = "", *, evidence: Optional[CancellationEvidence] = None
    ) -> None:
        super().__init__(message)
        self.evidence = evidence or CancellationEvidence()


class StepExecutor(Protocol):
    """Executes one saved plan step."""

    def execute_step(
        self,
        task: dict[str, Any],
        plan: dict[str, Any],
        step_index: int,
        step: dict[str, Any],
    ) -> StepResult: ...


class UnconnectedExecutor:
    """Default executor: no adapters connected yet (Phase 3)."""

    def execute_step(
        self,
        task: dict[str, Any],
        plan: dict[str, Any],
        step_index: int,
        step: dict[str, Any],
    ) -> StepResult:
        raise ValueError(
            f"No adapter connected for capability '{step.get('capability_key')}'."
        )


def execute_plan(
    task_id: str,
    plan: dict[str, Any],
    executor: Optional[StepExecutor] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> ExecutorOutcome:
    """Run saved plan steps in order and record step events.

    A ``DeviationReported`` saves the revised plan as the next version and
    returns a deviation outcome; the caller moves the task to
    ``waiting_reapproval``. ``TaskCancelled`` propagates to the caller.
    Any other error returns a failed outcome.
    """
    active_executor: StepExecutor = executor or UnconnectedExecutor()
    task = task_store.get_task(task_id, conn=conn)
    if task is None:
        raise FileNotFoundError(f"Task '{task_id}' not found.")
    inner = plan.get("plan")
    steps = inner.get("steps") if isinstance(inner, dict) else None
    if not isinstance(steps, list) or not steps:
        return ExecutorOutcome(kind="failed", error_summary="current plan has no steps")

    summaries: list[str] = []
    try:
        for step_index, step in enumerate(steps):
            try:
                result = active_executor.execute_step(task, plan, step_index, step)
            except (DeviationReported, TaskCancelled):
                raise
            except Exception as exc:
                logger.exception("Plan execution failed for task %s", task_id)
                task_store.clear_active_child(task_id, conn=conn)
                return ExecutorOutcome(kind="failed", error_summary=str(exc))
            summaries.append(result.summary)
            if result.child_kind and result.child_run_id:
                task_store.set_active_child(
                    task_id,
                    result.child_kind,
                    result.child_run_id,
                    conn=conn,
                )
            task_store.append_task_event(
                task_id,
                "capability_completed",
                {
                    "step_index": step_index,
                    "capability_key": result.capability_key,
                    "summary": result.summary,
                    "child_kind": result.child_kind,
                    "child_run_id": result.child_run_id,
                },
                conn=conn,
            )
    except DeviationReported as dev:
        revised = task_store.create_plan(
            task_id,
            dev.revised_plan,
            plan.get("approval_policy_snapshot", {}),
            conn=conn,
        )
        task_store.append_task_event(
            task_id,
            "note",
            {
                "text": f"deviation reported: {dev.reason}",
                "revised_plan_id": revised["plan_id"],
            },
            conn=conn,
        )
        task_store.clear_active_child(task_id, conn=conn)
        return ExecutorOutcome(
            kind="deviation",
            revised_plan=dev.revised_plan,
            deviation_reason=dev.reason,
        )
    task_store.clear_active_child(task_id, conn=conn)
    return ExecutorOutcome(kind="completed", result_summary="\n".join(summaries))
