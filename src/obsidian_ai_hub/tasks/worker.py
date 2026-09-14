"""Single serial Task worker: planning claims, execution claims, plan runs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.adapters import get_default_executor
from obsidian_ai_hub.tasks.execution import (
    StepExecutor,
    TaskCancelled,
    execute_plan,
)
from obsidian_ai_hub.tasks.planning import plan_task

logger = logging.getLogger(__name__)


def _process_one(instance_id: str, executor: Optional[StepExecutor] = None) -> bool:
    claimed = task_store.claim_task(instance_id, "planning")
    if claimed is not None:
        task_id = str(claimed["task_id"])
        try:
            result = plan_task(task_id)
        except ValueError as exc:
            # plan_task marks planner failures failed itself; other ValueErrors
            # (e.g. task left planning) need no further action either.
            logger.warning("Planner failed for task %s: %s", task_id, exc)
            return True
        except Exception as exc:
            logger.exception("Planner crashed for task %s", task_id)
            try:
                task_store.transition_task_status(
                    task_id, "failed", error_summary=str(exc)
                )
            except Exception:
                logger.exception("Failed to mark task %s failed", task_id)
            return True
        if result["outcome"] == "running":
            _run_execution(task_id, result["plan"], executor)
        return True
    claimed_exec = task_store.claim_task(instance_id, "execution")
    if claimed_exec is not None:
        task_id = str(claimed_exec["task_id"])
        try:
            plan = task_store.get_plan(str(claimed_exec["current_plan_id"]))
            if plan is None:
                task_store.transition_task_status(
                    task_id, "failed", error_summary="current plan missing"
                )
                return True
            _run_execution(task_id, plan, executor)
        except Exception as exc:
            logger.exception("Execution crashed for task %s", task_id)
            try:
                task_store.transition_task_status(
                    task_id, "failed", error_summary=str(exc)
                )
            except Exception:
                logger.exception("Failed to mark task %s failed", task_id)
        return True
    return False


def _run_execution(
    task_id: str, plan: dict[str, Any], executor: Optional[StepExecutor]
) -> None:
    if not _ensure_capabilities_enabled(task_id, plan):
        return
    active_executor: StepExecutor = executor or get_default_executor()
    from obsidian_ai_hub.tasks.directional import is_directional_plan
    from obsidian_ai_hub.tasks.orchestrator import run_directional_plan

    try:
        if is_directional_plan(plan.get("plan", {})):
            outcome = run_directional_plan(task_id, plan, active_executor)
        else:
            outcome = execute_plan(task_id, plan, active_executor)
    except TaskCancelled:
        task_store.clear_active_child(task_id)
        task_store.transition_task_status(task_id, "cancelling")
        task_store.transition_task_status(task_id, "cancelled")
        return
    if outcome.kind == "completed":
        task_store.transition_task_status(
            task_id, "completed", result_summary=outcome.result_summary
        )
    elif outcome.kind == "deviation":
        task_store.transition_task_status(task_id, "waiting_reapproval")
    else:
        task_store.transition_task_status(
            task_id, "failed", error_summary=outcome.error_summary
        )


def _ensure_capabilities_enabled(task_id: str, plan: dict[str, Any]) -> bool:
    """Stop before execution start when a planned capability is disabled.

    Creates a revised pending plan so the task waits in ``waiting_reapproval``
    instead of running with a capability the operator turned off.
    """
    capabilities = {c["capability_key"]: c for c in task_store.list_capabilities()}
    plan_inner = plan.get("plan", {}) or {}
    # Directional plans list approved capabilities; legacy plans list steps.
    if isinstance(plan_inner.get("capabilities"), list):
        keys = {
            str(entry.get("capability_key"))
            for entry in plan_inner["capabilities"]
            if isinstance(entry, dict)
        }
    else:
        steps = plan_inner.get("steps", [])
        keys = {
            str(step.get("capability_key"))
            for step in steps
            if isinstance(step, dict)
        }
    disabled = sorted(
        {
            key
            for key in keys
            if not capabilities.get(key, {}).get("enabled", False)
        }
    )
    if not disabled:
        return True
    task_store.create_plan(
        task_id,
        plan.get("plan", {}),
        plan.get("approval_policy_snapshot", {}),
    )
    task_store.append_task_event(
        task_id,
        "note",
        {"text": f"disabled capabilities block execution: {', '.join(disabled)}"},
    )
    task_store.transition_task_status(task_id, "waiting_reapproval")
    return False


async def task_worker_loop(
    instance_id: str,
    stop_event: asyncio.Event,
    poll_interval: float = 0.5,
    executor: Optional[StepExecutor] = None,
) -> None:
    """Poll claims serially until ``stop_event`` is set."""
    while not stop_event.is_set():
        try:
            did_work = await asyncio.to_thread(_process_one, instance_id, executor)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Task worker iteration failed")
            did_work = False
        if not did_work:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
