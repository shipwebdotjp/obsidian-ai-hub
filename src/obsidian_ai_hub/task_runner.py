from datetime import datetime, timedelta, time
import json
import logging
import shlex
import subprocess
from pathlib import Path

import yaml
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

DEFAULT_TASK_FILE = config.BASE_DIR / "tasks" / "tasks.yml"
LOCAL_TASK_FILE = config.BASE_DIR / "tasks" / "tasks.local.yml"
STATE_FILE = config.BASE_DIR / "tasks" / "last_run.json"

def compute_target(schedule: dict, now: datetime) -> datetime:
    t = schedule["type"]

    if t == "minutely":
        # 毎分 second 秒
        second = schedule.get("second", 0)
        candidate = now.replace(second=second, microsecond=0)
        if candidate > now:
            candidate -= timedelta(minutes=1)
        return candidate

    if t == "hourly":
        # 毎時 minute 分
        minute = schedule["minute"]
        candidate = now.replace(minute=minute, second=0, microsecond=0)
        if candidate > now:
            candidate -= timedelta(hours=1)
        return candidate

    if t == "daily":
        # 毎日 hour:minute
        hour = schedule["hour"]
        minute = schedule["minute"]
        candidate = datetime.combine(
            now.date(),
            time(hour, minute)
        )
        if candidate > now:
            candidate -= timedelta(days=1)
        return candidate

    if t == "weekly":
        # 毎週 weekday の hour:minute
        weekday = schedule["weekday"]  # 0=Mon
        hour = schedule["hour"]
        minute = schedule["minute"]

        today_weekday = now.weekday()
        delta_days = (today_weekday - weekday) % 7
        candidate_date = now.date() - timedelta(days=delta_days)
        candidate = datetime.combine(
            candidate_date,
            time(hour, minute)
        )
        if candidate > now:
            candidate -= timedelta(days=7)
        return candidate

    if t == "monthly":
        # 毎月 day の hour:minute
        day = schedule["day"]
        hour = schedule["hour"]
        minute = schedule["minute"]

        year = now.year
        month = now.month

        def make_candidate(y, m):
            return datetime(y, m, day, hour, minute)

        try:
            candidate = make_candidate(year, month)
        except ValueError:
            # 31日など存在しない日はスキップ → 前月
            month -= 1
            if month == 0:
                month = 12
                year -= 1
            candidate = make_candidate(year, month)

        if candidate > now:
            month -= 1
            if month == 0:
                month = 12
                year -= 1
            candidate = make_candidate(year, month)

        return candidate

    raise ValueError(f"unknown schedule type: {t}")

def load_tasks():
    task_file = LOCAL_TASK_FILE if LOCAL_TASK_FILE.exists() else DEFAULT_TASK_FILE
    with task_file.open() as f:
        return yaml.safe_load(f)


def load_state():
    if STATE_FILE.exists():
        with STATE_FILE.open() as f:
            return {
                k: datetime.fromisoformat(v)
                for k, v in json.load(f).items()
            }
    return {}


def save_state(state):
    with STATE_FILE.open("w") as f:
        json.dump(
            {k: v.isoformat() for k, v in state.items()},
            f,
            indent=2,
        )


def run_command(command):
    """Run a scheduled command without invoking a shell.

    Supports the existing task format with optional "cd <path> && ..." chains.
    Each segment is parsed with shlex and executed with shell=False.
    """
    cwd = None
    segments = [segment.strip() for segment in str(command).split("&&") if segment.strip()]
    if not segments:
        return

    for segment in segments:
        parts = shlex.split(segment)
        if not parts:
            continue

        if parts[0] == "cd":
            if len(parts) != 2:
                raise ValueError(f"Unsupported cd segment: {segment}")
            cwd = parts[1]
            continue

        subprocess.run(parts, cwd=cwd, check=False)


def main():
    now = datetime.now()
    tasks = load_tasks()
    state = load_state()

    for task in tasks:
        if not task.get("enabled", True):
            continue

        task_id = task["id"]
        schedule = task["schedule"]
        command = task["command"]

        last_run = state.get(task_id, datetime.min)
        target = compute_target(schedule, now)

        if last_run < target <= now:
            logger.info("Running task: %s", task_id)
            run_command(command)
            state[task_id] = now

    save_state(state)


if __name__ == "__main__":
    main()

