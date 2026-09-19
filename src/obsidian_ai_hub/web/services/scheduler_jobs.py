import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SchedulerJobConfigConflictError(ValueError):
    def __init__(self, message="Conflict: Scheduler job configuration has been updated by another session. Please refresh."):
        super().__init__(message)


# --- Recurring Job services ---

def get_recurring_jobs() -> dict:
    from obsidian_ai_hub.scheduler_jobs.recurring import (
        get_jobs_file_and_revision_locked,
        get_command_preset_info,
        get_agent_source,
        compute_next_target,
    )
    filepath, sha, jobs = get_jobs_file_and_revision_locked()

    job_items = []
    now = datetime.now()

    for t in jobs:
        # Resolve preset info
        preset_info = get_command_preset_info(t.get("command", ""))

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
            "command": t.get("command"),
            "is_preset": preset_info["is_preset"],
            "preset_flag": preset_info["flag"],
            "preset_name": preset_info["name"],
            "next_run": next_run_str,
            # Corrupt/missing sources are hidden rather than failing the list.
            "agent_source": get_agent_source(t),
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
        validate_jobs,
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


# --- Job State services ---

def list_job_states() -> list[dict[str, Any]]:
    from obsidian_ai_hub.utils import execution_logger

    return execution_logger.list_job_states()
