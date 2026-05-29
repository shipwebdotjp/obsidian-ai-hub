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

def parse_cron_field(value, min_val, max_val) -> set[int]:
    if isinstance(value, int):
        if not (min_val <= value <= max_val):
            raise ValueError(f"Value {value} out of range [{min_val}, {max_val}]")
        return {value}

    if isinstance(value, list):
        result = set()
        for v in value:
            result.update(parse_cron_field(v, min_val, max_val))
        if not result:
            raise ValueError("Empty list in cron field")
        return result

    if not isinstance(value, str):
        raise ValueError(f"Invalid type for cron field: {type(value)}")

    if "," in value:
        result = set()
        for part in value.split(","):
            result.update(parse_cron_field(part.strip(), min_val, max_val))
        if not result:
            raise ValueError(f"Empty cron field: {value}")
        return result

    if "/" in value:
        base, step_str = value.split("/", 1)
        try:
            step = int(step_str)
        except ValueError as err:
            raise ValueError(f"Invalid step: {step_str}") from err
        if step <= 0:
            raise ValueError(f"Step must be positive: {step}")

        if base == "*":
            start, end = min_val, max_val
        elif "-" in base:
            start_str, end_str = base.split("-")
            try:
                start, end = int(start_str), int(end_str)
            except ValueError as err:
                raise ValueError(f"Invalid range in step: {base}") from err
        else:
            try:
                start = int(base)
            except ValueError as err:
                raise ValueError(f"Invalid base in step: {base}") from err
            end = max_val

        if not (min_val <= start <= max_val) or not (min_val <= end <= max_val):
            raise ValueError(f"Range out of bounds: {base} for [{min_val}, {max_val}]")
        if start > end:
            raise ValueError(f"Invalid range: {start}-{end}")

        return set(range(start, end + 1, step))

    if "-" in value:
        start_str, end_str = value.split("-")
        try:
            start, end = int(start_str), int(end_str)
        except ValueError as err:
            raise ValueError(f"Invalid range: {value}") from err
        if not (min_val <= start <= max_val) or not (min_val <= end <= max_val):
            raise ValueError(f"Range out of bounds: {value} for [{min_val}, {max_val}]")
        if start > end:
            raise ValueError(f"Invalid range: {start}-{end}")
        return set(range(start, end + 1))

    if value == "*":
        return set(range(min_val, max_val + 1))

    try:
        val = int(value)
        if not (min_val <= val <= max_val):
            raise ValueError(f"Value {val} out of range [{min_val}, {max_val}]")
        return {val}
    except ValueError as err:
        raise ValueError(f"Invalid cron field value: {value}") from err


def compute_target(schedule: dict, now: datetime) -> datetime:
    t = schedule["type"]
    if t not in ["minutely", "hourly", "daily", "weekly", "monthly"]:
        raise ValueError(f"unknown schedule type: {t}")

    now = now.replace(microsecond=0)

    # 許容値の集合を定義（降順ソート済みリストとして保持）
    seconds = sorted(list(parse_cron_field(schedule.get("second", 0), 0, 59)), reverse=True)
    minutes = sorted(list(parse_cron_field(schedule.get("minute", 0), 0, 59)), reverse=True)
    hours = sorted(list(parse_cron_field(schedule.get("hour", 0), 0, 23)), reverse=True)
    days = sorted(list(parse_cron_field(schedule.get("day", 1), 1, 31)), reverse=True)
    weekdays = parse_cron_field(schedule.get("weekday", "*"), 0, 6)

    def is_valid(dt: datetime) -> bool:
        if dt.second not in seconds:
            return False
        if t == "minutely":
            return True
        if dt.minute not in minutes:
            return False
        if t == "hourly":
            return True
        if dt.hour not in hours:
            return False
        if t == "daily":
            return True
        if t == "weekly":
            return dt.weekday() in weekdays
        if t == "monthly":
            return dt.day in days
        return False

    curr = now
    while True:
        if is_valid(curr):
            return curr

        # フィールドごとに効率的に戻る
        if curr.second not in seconds:
            next_s = next((s for s in seconds if s < curr.second), None)
            if next_s is not None:
                curr = curr.replace(second=next_s)
            else:
                curr = (curr - timedelta(minutes=1)).replace(second=seconds[0])
            continue

        if t == "minutely":
            curr -= timedelta(minutes=1)
            curr = curr.replace(second=seconds[0])
            continue

        if curr.minute not in minutes:
            next_m = next((m for m in minutes if m < curr.minute), None)
            if next_m is not None:
                curr = curr.replace(minute=next_m, second=seconds[0])
            else:
                curr = (curr - timedelta(hours=1)).replace(minute=minutes[0], second=seconds[0])
            continue

        if t == "hourly":
            curr -= timedelta(hours=1)
            curr = curr.replace(minute=minutes[0], second=seconds[0])
            continue

        if curr.hour not in hours:
            next_h = next((h for h in hours if h < curr.hour), None)
            if next_h is not None:
                curr = curr.replace(hour=next_h, minute=minutes[0], second=seconds[0])
            else:
                curr = (curr - timedelta(days=1)).replace(hour=hours[0], minute=minutes[0], second=seconds[0])
            continue

        if t == "daily":
            curr -= timedelta(days=1)
            curr = curr.replace(hour=hours[0], minute=minutes[0], second=seconds[0])
            continue

        # weekly と monthly は1日ずつ戻る
        curr -= timedelta(days=1)
        curr = curr.replace(hour=hours[0], minute=minutes[0], second=seconds[0])

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

