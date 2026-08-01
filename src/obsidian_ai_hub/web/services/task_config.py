import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class TaskConfigConflictError(ValueError):
    def __init__(self, message="Conflict: Task configuration has been updated by another session. Please refresh."):
        super().__init__(message)


# --- Task Config services ---

def get_task_config() -> dict:
    from obsidian_ai_hub.task_runner import (
        get_tasks_file_and_revision_locked,
        get_command_preset_info,
        compute_next_target,
    )
    filepath, sha, tasks = get_tasks_file_and_revision_locked()

    task_items = []
    now = datetime.now()

    for t in tasks:
        # Resolve preset info
        preset_info = get_command_preset_info(t.get("command", ""))

        # Calculate next execution explanation
        next_run_str = None
        try:
            next_run = compute_next_target(t.get("schedule", {}), now)
            next_run_str = next_run.isoformat()
        except Exception as e:
            logger.debug("Failed to compute next target for task %s: %s", t.get("id"), e, exc_info=True)

        task_items.append({
            "id": t.get("id"),
            "enabled": t.get("enabled", True),
            "schedule": t.get("schedule"),
            "command": t.get("command"),
            "is_preset": preset_info["is_preset"],
            "preset_flag": preset_info["flag"],
            "preset_name": preset_info["name"],
            "next_run": next_run_str,
        })

    return {
        "tasks": task_items,
        "filepath": str(filepath),
        "revision": sha,
    }


def update_task_config(revision: str, tasks: list) -> dict:
    from obsidian_ai_hub.task_runner import (
        acquire_task_config_lock,
        get_tasks_file_and_revision,
        validate_tasks,
        save_tasks_and_arm,
    )

    with acquire_task_config_lock():
        _, current_sha, old_tasks = get_tasks_file_and_revision()

        if revision != current_sha:
            raise TaskConfigConflictError()

        # Validate tasks
        validate_tasks(tasks)

        # Arm changed tasks and save atomically
        save_tasks_and_arm(tasks, old_tasks, datetime.now())

        # Reload to get the new sha
        _, new_sha, _ = get_tasks_file_and_revision()

    return {
        "success": True,
        "revision": new_sha,
    }


def preview_command(command: str) -> dict:
    from obsidian_ai_hub.task_runner import (
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
