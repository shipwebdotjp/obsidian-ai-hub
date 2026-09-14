"""Task Agent services for the web layer (thin wrappers over tasks.store)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from obsidian_ai_hub.tasks import store as task_store

logger = logging.getLogger(__name__)


def list_task_agent_tasks(
    status: Optional[str] = None, limit: int = 50, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    items = task_store.list_tasks(status=status, limit=limit, offset=offset)
    total = task_store.count_tasks(status=status)
    return items, total


def create_task_agent_task(prompt_text: str) -> dict[str, Any]:
    """Create a task in ``queued`` status via the Task intake receipt path."""
    return task_store.create_task(prompt_text)


def get_task_agent_task_detail(task_id: str) -> Optional[dict[str, Any]]:
    task = task_store.get_task(task_id)
    if task is None:
        return None
    return {
        "task": task,
        "plans": task_store.list_plans(task_id),
        "events": task_store.list_task_events(task_id),
    }


def approve_task_agent_task(task_id: str) -> dict[str, Any]:
    task = task_store.get_task(task_id)
    if task is None:
        raise FileNotFoundError(f"Task '{task_id}' not found.")
    if str(task["status"]) not in ("waiting_approval", "waiting_reapproval"):
        raise ValueError(
            f"Task '{task_id}' is not waiting for approval (now '{task['status']}')."
        )
    return task_store.decide_plan(task_id, "approve")


def reject_task_agent_task(task_id: str, reason: str) -> dict[str, Any]:
    task = task_store.get_task(task_id)
    if task is None:
        raise FileNotFoundError(f"Task '{task_id}' not found.")
    if str(task["status"]) not in ("waiting_approval", "waiting_reapproval"):
        raise ValueError(
            f"Task '{task_id}' is not waiting for approval (now '{task['status']}')."
        )
    return task_store.decide_plan(task_id, "reject", reason=reason)


def cancel_task_agent_task(task_id: str) -> dict[str, Any]:
    """Cancel a task: immediate unless it is running with a child to stop."""
    task = task_store.get_task(task_id)
    if task is None:
        raise FileNotFoundError(f"Task '{task_id}' not found.")
    status = str(task["status"])
    if status in task_store.TASK_TERMINAL_STATUSES:
        raise ValueError(f"Task '{task_id}' is already terminal ('{status}').")
    if status == "cancelling":
        return task
    if status == "running":
        updated = task_store.transition_task_status(task_id, "cancelling")
        _request_child_cancel(task)
        return updated
    return task_store.transition_task_status(task_id, "cancelled")


def _request_child_cancel(task: dict[str, Any]) -> None:
    """Best-effort cancel of the active child run (adapter loop also watches)."""
    child_kind = task.get("active_child_kind")
    child_run_id = task.get("active_child_run_id")
    if not child_kind or not child_run_id:
        return
    try:
        if child_kind == "agent":
            from obsidian_ai_hub.agents import store as agent_store

            agent_store.request_cancel_run(str(child_run_id))
        elif child_kind == "coding":
            from obsidian_ai_hub.coding import store as coding_store

            coding_store.request_cancel_run(str(child_run_id))
        else:
            logger.warning(
                "Unknown child kind '%s' for task %s", child_kind, task["task_id"]
            )
    except Exception:
        logger.exception("Child cancel request failed for task %s", task["task_id"])


def replan_task_agent_task(task_id: str) -> dict[str, Any]:
    """Return an ``interrupted`` task to ``queued`` (explicit replan only)."""
    task = task_store.get_task(task_id)
    if task is None:
        raise FileNotFoundError(f"Task '{task_id}' not found.")
    if str(task["status"]) != "interrupted":
        raise ValueError(
            f"Only interrupted tasks can be replanned (now '{task['status']}')."
        )
    return task_store.transition_task_status(task_id, "queued")


def _enrich_capability(row: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    definition = catalog.get(row["capability_key"])
    return {
        **row,
        "label": definition.label if definition else row["capability_key"],
        "description": definition.description if definition else "",
    }


def _capability_catalog() -> dict[str, Any]:
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

    return {d.key: d for d in get_capability_definitions()}


def list_task_agent_capabilities() -> list[dict[str, Any]]:
    catalog = _capability_catalog()
    return [_enrich_capability(row, catalog) for row in task_store.list_capabilities()]


def update_task_agent_capability(
    capability_key: str,
    enabled: Optional[bool] = None,
    approval_policy: Optional[str] = None,
) -> dict[str, Any]:
    row = task_store.update_capability(
        capability_key, enabled=enabled, approval_policy=approval_policy
    )
    return _enrich_capability(row, _capability_catalog())
