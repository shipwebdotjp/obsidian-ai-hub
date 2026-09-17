"""Scheduler Job domain package.

Recurring jobs (YAML-defined, schedule-driven) and one-shot jobs
(SQLite queue, run once) share this package. They are a separate
bounded context from the Task Agent Task aggregate.
"""

from obsidian_ai_hub.scheduler_jobs.recurring import (
    acquire_job_config_lock,
    compute_next_target,
    compute_target,
    get_command_preset_info,
    get_jobs_file_and_revision,
    get_jobs_file_and_revision_locked,
    load_jobs,
    load_state,
    parse_command,
    save_jobs_and_arm,
    save_state,
    validate_jobs,
)

__all__ = [
    "acquire_job_config_lock",
    "compute_next_target",
    "compute_target",
    "get_command_preset_info",
    "get_jobs_file_and_revision",
    "get_jobs_file_and_revision_locked",
    "load_jobs",
    "load_state",
    "parse_command",
    "save_jobs_and_arm",
    "save_state",
    "validate_jobs",
]
