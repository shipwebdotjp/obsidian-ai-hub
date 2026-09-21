"""Task Agent services for the web layer (thin wrappers over tasks.store)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from obsidian_ai_hub.tasks import store as task_store

logger = logging.getLogger(__name__)


NON_TERMINAL_FILTER = "__non_terminal__"
"""Frontend sentinel: list every task that is not in a terminal state."""

# Workflow capability-node bridge tasks are internal execution rows; the
# Task Agent list never shows them (direct detail URLs still resolve).
EXCLUDED_ORIGINS = frozenset({task_store.TASK_ORIGIN_WORKFLOW})


def list_task_agent_tasks(
    status: Optional[str] = None, limit: int = 50, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    if status == NON_TERMINAL_FILTER:
        exclude = set(task_store.TASK_TERMINAL_STATUSES)
        items = task_store.list_tasks(
            limit=limit,
            offset=offset,
            exclude_statuses=exclude,
            exclude_origins=EXCLUDED_ORIGINS,
        )
        total = task_store.count_tasks(
            exclude_statuses=exclude, exclude_origins=EXCLUDED_ORIGINS
        )
        return items, total
    items = task_store.list_tasks(
        status=status, limit=limit, offset=offset, exclude_origins=EXCLUDED_ORIGINS
    )
    total = task_store.count_tasks(status=status, exclude_origins=EXCLUDED_ORIGINS)
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


_TASK_TARGET_CHANGE_STATUSES = ("waiting_approval", "waiting_reapproval")


def set_task_agent_project_resolution(
    task_id: str, kind: str, project_id: Optional[int] = None
) -> dict[str, Any]:
    """Change a pending plan's target and requeue the task for replanning.

    Accepted only in the waiting-approval states. Records the normalized
    human selection as a ``target_resolution_selected`` event (no
    confidence), supersedes the current pending plan, and returns the task
    to ``queued`` so the next planning round builds a new plan on the
    human-selected target. Invalid or deleted projects are rejected.
    """
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub.tasks import planning as task_planning

    task = task_store.get_task(task_id)
    if task is None:
        raise FileNotFoundError(f"Task '{task_id}' not found.")
    status = str(task["status"])
    if status not in _TASK_TARGET_CHANGE_STATUSES:
        raise ValueError(
            f"Task '{task_id}' target can only be changed while waiting for "
            f"approval (now '{status}')."
        )
    # One transaction for all three writes: a failure (concurrent status
    # change, DB error) must not leave a superseded plan with an orphan
    # selection, or vice versa.
    conn = get_db_connection()
    try:
        with conn:
            task_planning.record_target_resolution_selection(
                task_id,
                kind=kind,
                project_id=project_id,
                via="plan_screen",
                conn=conn,
            )
            task_store.supersede_pending_plans(task_id, conn=conn)
            task_store.transition_task_status(task_id, "queued", conn=conn)
    finally:
        conn.close()
    updated = task_store.get_task(task_id)
    if updated is None:
        raise FileNotFoundError(f"Task '{task_id}' not found after update.")
    return updated


def list_task_agent_target_options() -> list[dict[str, Any]]:
    """Return the selectable targets: valid Git projects only."""
    from obsidian_ai_hub.tasks import planning as task_planning

    options: list[dict[str, Any]] = []
    for project in task_planning.list_valid_projects():
        try:
            project_id = int(project.get("project_id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if project_id <= 0:
            continue
        options.append(
            {
                "project_id": project_id,
                "name": str(project.get("name") or ""),
                "git_root": str(project.get("git_root") or ""),
                "keywords": [str(k) for k in (project.get("keywords") or [])],
            }
        )
    return options


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
