"""Scheduler job runner entry point (recurring + one-shot)."""

import argparse
import fcntl
import logging
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def run_cycle(now: datetime | None = None) -> dict:
    """Run one scheduler cycle: recurring due jobs, then due one-shot jobs."""
    from obsidian_ai_hub.scheduler_jobs import recurring

    now = now or datetime.now()
    recurring.assert_no_legacy_task_files()

    recurring.RUNNER_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    runner_f = open(recurring.RUNNER_LOCK_FILE, "w")
    try:
        try:
            fcntl.flock(runner_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            logger.info("Another scheduler runner is already running. Exiting.")
            return {"recurring": [], "one_shot": [], "skipped": True}
        return _run_cycle_locked(now)
    finally:
        runner_f.close()


def _run_cycle_locked(now: datetime) -> dict:
    from obsidian_ai_hub.scheduler_jobs import one_shot, recurring

    with recurring.acquire_job_config_lock():
        jobs = recurring.load_jobs()

    ran_recurring: list[str] = []
    for job in jobs or []:
        if not isinstance(job, dict):
            logger.warning("Skipping malformed job entry (not an object): %r", job)
            continue
        if not job.get("enabled", True):
            continue
        job_id = job.get("id")
        schedule = job.get("schedule")
        workflow_target = recurring.get_workflow_target(job)
        command = job.get("command")
        if not job_id or not isinstance(schedule, dict) or not (command or workflow_target):
            logger.warning(
                "Skipping malformed job entry (missing id/schedule/target): %r", job
            )
            continue

        try:
            with recurring.acquire_job_config_lock():
                current_state = recurring.load_state()
                from datetime import datetime as _dt

                last_run = current_state.get(job_id, _dt.min)

            target = recurring.compute_target(schedule, now)
        except Exception:
            logger.exception("Skipping job with invalid schedule/state: %s", job_id)
            continue

        if last_run < target <= now:
            logger.info("Running job: %s", job_id)
            if workflow_target is not None:
                # A workflow dispatch consumes the slot whether it succeeds or
                # fails: the next slot re-resolves the latest published Revision.
                from obsidian_ai_hub.workflow import scheduling

                try:
                    dispatch, _ = scheduling.dispatch_recurring_slot(
                        job_id,
                        target.isoformat(),
                        workflow_target.get("workflow_id"),
                        workflow_target.get("inputs") or {},
                    )
                    if dispatch.get("status") == scheduling.FAILED:
                        logger.warning(
                            "Workflow job %s dispatch failed for %s: %s",
                            job_id,
                            target.isoformat(),
                            dispatch.get("failure_reason"),
                        )
                except Exception:
                    logger.exception(
                        "Workflow job dispatch errored; slot will retry: %s", job_id
                    )
                    continue
            else:
                try:
                    recurring.run_command(command)
                except Exception:
                    logger.exception(
                        "Recurring job failed (state not updated, will retry): %s",
                        job_id,
                    )
                    continue
            with recurring.acquire_job_config_lock():
                current_state = recurring.load_state()
                current_state[job_id] = now
                recurring.save_state(current_state)
            ran_recurring.append(job_id)

    interrupted = one_shot.mark_interrupted_orphans()
    if interrupted:
        logger.info("Marked %d orphaned one-shot job(s) as interrupted", interrupted)
    finished = one_shot.run_due_one_shot_jobs()
    try:
        pruned = one_shot.prune_expired_one_shot_jobs()
    except Exception:
        logger.warning("Failed to prune expired one-shot jobs", exc_info=True)
        pruned = 0

    return {
        "recurring": ran_recurring,
        "one_shot": [j["job_id"] for j in finished],
        "interrupted": interrupted,
        "pruned": pruned,
        "skipped": False,
    }


def spawn_cycle_process() -> Optional[int]:
    """Start a detached one-off runner process, best effort.

    Used by the Web UI "run now" flow so a queued one-shot job does not wait
    for the next launchd interval. The runner lock keeps this process and the
    launchd runner from running cycles concurrently; when the lock is taken the
    spawned process exits immediately and the queued job is picked up by the
    next scheduled cycle. Returns the PID, or ``None`` when spawning is
    skipped (test env) or fails.
    """
    from obsidian_ai_hub.utils import config

    if config.IS_TEST_ENV:
        return None

    project_root = Path(config.BASE_DIR)
    args = [sys.executable, "-m", "obsidian_ai_hub.job_runner"]
    wrapper = project_root / "scripts" / "launchd_log_wrapper.sh"
    if wrapper.is_file():
        cmd = ["/bin/bash", str(wrapper), "obsidian_merge", *args]
    else:
        cmd = args
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        logger.warning("Failed to spawn an immediate job_runner cycle", exc_info=True)
        return None
    # Web は長時間生き続けるため、子を reaping しないと zombie が残る。
    threading.Thread(target=proc.wait, daemon=True).start()
    logger.info("Spawned immediate job_runner cycle (pid=%s)", proc.pid)
    return proc.pid


def main() -> None:
    parser = argparse.ArgumentParser(description="Scheduler job runner")
    parser.add_argument(
        "--migrate-tasks-to-jobs",
        action="store_true",
        help="One-shot YAML migration: tasks/ -> jobs/, then exit.",
    )
    args = parser.parse_args()

    if args.migrate_tasks_to_jobs:
        from obsidian_ai_hub.scheduler_jobs.recurring import migrate_tasks_yaml_to_jobs

        dest = migrate_tasks_yaml_to_jobs()
        print(f"Migrated Scheduler Task YAML to {dest}")
        return

    run_cycle()


if __name__ == "__main__":
    main()
