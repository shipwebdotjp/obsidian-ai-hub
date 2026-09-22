import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SchedulerJobConfigConflictError(ValueError):
    def __init__(self, message="Conflict: Scheduler job configuration has been updated by another session. Please refresh."):
        super().__init__(message)


# --- Recurring Job services ---

def _workflow_item(target: dict) -> Optional[dict]:
    """Build the response target, or None when the raw YAML is unusable.

    A hand-edited ``workflow:`` mapping without a non-empty ``workflow_id``
    must not fail the whole list response (same intent as hiding a corrupt
    ``agent_source``).
    """
    from obsidian_ai_hub.workflow import scheduling
    from obsidian_ai_hub.workflow.store import get_workflow

    workflow_id = target.get("workflow_id")
    if not isinstance(workflow_id, str) or not workflow_id.strip():
        return None
    workflow = get_workflow(workflow_id)
    revision = scheduling.resolve_published_revision(workflow_id)
    return {
        "workflow_id": workflow_id,
        "inputs": target.get("inputs") or {},
        "workflow_name": workflow.get("name") if workflow else None,
        "published_revision_id": revision.get("revision_id") if revision else None,
    }


def get_recurring_jobs() -> dict:
    from obsidian_ai_hub.scheduler_jobs.recurring import (
        get_jobs_file_and_revision_locked,
        get_command_preset_info,
        get_agent_source,
        get_workflow_target,
        compute_next_target,
    )
    from obsidian_ai_hub.workflow import scheduling

    filepath, sha, jobs = get_jobs_file_and_revision_locked()

    job_items = []
    now = datetime.now()

    job_ids = [t.get("id") for t in jobs if t.get("id")]
    try:
        latest_dispatches = scheduling.list_dispatches(job_ids)
    except Exception:
        logger.debug("Failed to load dispatches", exc_info=True)
        latest_dispatches = {}

    for t in jobs:
        command = t.get("command")
        workflow_target = get_workflow_target(t)
        preset_info = (
            get_command_preset_info(command)
            if command
            else {"is_preset": False, "flag": None, "name": None}
        )

        # Calculate next execution explanation
        next_run_str = None
        try:
            next_run = compute_next_target(t.get("schedule", {}), now)
            next_run_str = next_run.isoformat()
        except Exception as e:
            logger.debug("Failed to compute next target for job %s: %s", t.get("id"), e, exc_info=True)

        job_items.append({
            "id": t.get("id"),
            "enabled": t.get("enabled", True),
            "schedule": t.get("schedule"),
            "command": command,
            "workflow": _workflow_item(workflow_target) if workflow_target else None,
            "is_preset": preset_info["is_preset"],
            "preset_flag": preset_info["flag"],
            "preset_name": preset_info["name"],
            "next_run": next_run_str,
            # Corrupt/missing sources are hidden rather than failing the list.
            "agent_source": get_agent_source(t),
            "latest_dispatch": latest_dispatches.get(t.get("id")),
        })

    return {
        "jobs": job_items,
        "filepath": str(filepath),
        "revision": sha,
    }


def update_recurring_jobs(revision: str, jobs: list) -> dict:
    from obsidian_ai_hub.scheduler_jobs.recurring import (
        acquire_job_config_lock,
        get_jobs_file_and_revision,
        get_workflow_target,
        validate_jobs,
        validate_workflow_target,
        merge_recurring_jobs,
        save_jobs_and_arm,
    )

    with acquire_job_config_lock():
        _, current_sha, old_jobs = get_jobs_file_and_revision()

        # Revision check must precede any merge/validation/save so a stale
        # client can never partially apply its payload.
        if revision != current_sha:
            raise SchedulerJobConfigConflictError()

        # Merge against the current raw YAML: preserve unknown metadata, drop
        # agent_source on meaningful human edits, and never trust a
        # client-supplied agent_source.
        merged_jobs = merge_recurring_jobs(old_jobs, jobs)
        validate_jobs(merged_jobs)

        # A workflow target must reference a published Revision with matching
        # inputs; reject the whole PUT before any write so the UI cannot save a
        # job that could never dispatch.
        for job in merged_jobs:
            target = get_workflow_target(job)
            if target is not None:
                validate_workflow_target(
                    target.get("workflow_id"), target.get("inputs")
                )

        # Arm changed jobs and save atomically
        save_jobs_and_arm(merged_jobs, old_jobs, datetime.now())

        # Reload to get the new sha
        _, new_sha, _ = get_jobs_file_and_revision()

    return {
        "success": True,
        "revision": new_sha,
    }


def preview_command(command: str) -> dict:
    from obsidian_ai_hub.scheduler_jobs.recurring import (
        parse_command,
        get_command_preset_info,
    )
    segments = parse_command(command)
    preset_info = get_command_preset_info(command)
    return {
        "segments": segments,
        "is_preset": preset_info["is_preset"],
        "preset_flag": preset_info["flag"],
        "preset_name": preset_info["name"],
    }


# --- One-shot Job services ---

def _to_summary(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row.pop("segments", None)
    row["output_truncated"] = bool(row.get("output_truncated"))
    return row


def list_one_shot_jobs(limit: int = 100, offset: int = 0) -> dict:
    from obsidian_ai_hub.scheduler_jobs import one_shot

    items, total = one_shot.list_one_shot_jobs(limit=limit, offset=offset)
    return {"items": [_to_summary(i) for i in items], "total": total}


def get_one_shot_job_detail(job_id: str) -> Optional[dict]:
    from obsidian_ai_hub.scheduler_jobs import one_shot

    row = one_shot.get_one_shot_job(job_id)
    if row is None:
        return None
    detail = dict(row)
    detail["output_truncated"] = bool(detail.get("output_truncated"))
    return detail


def cancel_one_shot_job(job_id: str) -> dict:
    from obsidian_ai_hub.scheduler_jobs import one_shot

    try:
        row = one_shot.cancel_one_shot_job(job_id)
    except LookupError as e:
        raise KeyError(str(e)) from e
    return _to_summary(row)


def create_one_shot_workflow_job(workflow_id: str, inputs: dict, run_at: Optional[str]) -> dict:
    from obsidian_ai_hub.scheduler_jobs import one_shot

    try:
        row = one_shot.register_one_shot_workflow_job(
            workflow_id, inputs, run_at
        )
    except ValueError as e:
        raise ValueError(str(e)) from e
    return _to_summary(row)


# --- Job State services ---

def list_job_states() -> list[dict[str, Any]]:
    from obsidian_ai_hub.utils import execution_logger

    return execution_logger.list_job_states()
