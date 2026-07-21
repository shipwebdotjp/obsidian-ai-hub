import contextlib
import fcntl
import hashlib
import json
import logging
import os
import shlex
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

TEST_TASK_FILE = config.BASE_DIR / "tasks" / "tasks.test.yml"
DEFAULT_TASK_FILE = config.BASE_DIR / "tasks" / "tasks.yml"
LOCAL_TASK_FILE = config.BASE_DIR / "tasks" / "tasks.local.yml"
STATE_FILE = config.TASK_RUN_STATE_PATH

LOCK_FILE = STATE_FILE.parent / ".task-config.lock"
RUNNER_LOCK_FILE = STATE_FILE.parent / ".task-runner.lock"

PRESET_FLAGS = {
    "--merge-inbox": "Inbox merge",
    "--summerize-day": "日サマリ",
    "--summerize-week": "週サマリ",
    "--summerize-month": "月サマリ",
    "--make-target": "目標作成",
    "--write-today-schedule": "今日の予定・タスクを書き込み",
    "--notify-today-schedule": "今日の予定通知",
    "--backup": "Backup",
    "--sync-vault": "Vault sync",
    "--sync-people": "People sync",
    "--sync-knowledge": "Knowledge sync",
    "--review-draft": "Review draft",
    "--memory-extract": "Memory extract",
    "--suggest-research-theme": "Research suggestion",
    "--log-activity": "Activity log",
}


@contextlib.contextmanager
def acquire_task_config_lock():
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def atomic_write(filepath: Path, content: str):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=filepath.parent, delete=False, encoding="utf-8") as tf:
        tf.write(content)
        temp_name = tf.name
    try:
        os.replace(temp_name, filepath)
    except Exception:
        if os.path.exists(temp_name):
            os.remove(temp_name)
        raise


def atomic_write_json(filepath: Path, data: dict):
    content = json.dumps(data, indent=2, ensure_ascii=False)
    atomic_write(filepath, content)


def atomic_write_yaml(filepath: Path, data: list):
    content = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    atomic_write(filepath, content)


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


def normalize_schedule(schedule: dict) -> dict:
    t = schedule.get("type")
    if t not in ["minutely", "hourly", "daily", "weekly", "monthly"]:
        raise ValueError(f"unknown schedule type: {t}")

    normalized = {"type": t}

    fields_config = {}
    if t == "minutely":
        fields_config = {"second": (0, 59, 0)}
    elif t == "hourly":
        fields_config = {"second": (0, 59, 0), "minute": (0, 59, 0)}
    elif t == "daily":
        fields_config = {"second": (0, 59, 0), "minute": (0, 59, 0), "hour": (0, 23, 0)}
    elif t == "weekly":
        fields_config = {"second": (0, 59, 0), "minute": (0, 59, 0), "hour": (0, 23, 0), "weekday": (0, 6, "*")}
    elif t == "monthly":
        fields_config = {"second": (0, 59, 0), "minute": (0, 59, 0), "hour": (0, 23, 0), "day": (1, 31, 1)}

    allowed_keys = set(fields_config.keys()) | {"type"}
    extra_keys = set(schedule.keys()) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unrelated fields for schedule type '{t}': {', '.join(extra_keys)}")

    for field, (min_val, max_val, default) in fields_config.items():
        val = schedule.get(field, default)
        parsed_set = parse_cron_field(val, min_val, max_val)
        normalized[field] = sorted(list(parsed_set))

    return normalized


def _find_target(schedule: dict, now: datetime, forward: bool) -> datetime:
    t = schedule.get("type")
    if t not in ["minutely", "hourly", "daily", "weekly", "monthly"]:
        raise ValueError(f"unknown schedule type: {t}")

    now = now.replace(microsecond=0)

    seconds = sorted(list(parse_cron_field(schedule.get("second", 0), 0, 59)), reverse=not forward)
    minutes = sorted(list(parse_cron_field(schedule.get("minute", 0), 0, 59)), reverse=not forward)
    hours = sorted(list(parse_cron_field(schedule.get("hour", 0), 0, 23)), reverse=not forward)
    days = sorted(list(parse_cron_field(schedule.get("day", 1), 1, 31)), reverse=not forward)
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

    delta_sec = 1 if forward else 0
    curr = now + timedelta(seconds=delta_sec) if forward else now
    step_sign = 1 if forward else -1

    while True:
        if is_valid(curr):
            return curr

        if curr.second not in seconds:
            next_s = next((s for s in seconds if (s > curr.second if forward else s < curr.second)), None)
            if next_s is not None:
                curr = curr.replace(second=next_s)
            else:
                curr = (curr + step_sign * timedelta(minutes=1)).replace(second=seconds[0])
            continue

        if t == "minutely":
            curr += step_sign * timedelta(minutes=1)
            curr = curr.replace(second=seconds[0])
            continue

        if curr.minute not in minutes:
            next_m = next((m for m in minutes if (m > curr.minute if forward else m < curr.minute)), None)
            if next_m is not None:
                curr = curr.replace(minute=next_m, second=seconds[0])
            else:
                curr = (curr + step_sign * timedelta(hours=1)).replace(
                    minute=minutes[0], second=seconds[0]
                )
            continue

        if t == "hourly":
            curr += step_sign * timedelta(hours=1)
            curr = curr.replace(minute=minutes[0], second=seconds[0])
            continue

        if curr.hour not in hours:
            next_h = next((h for h in hours if (h > curr.hour if forward else h < curr.hour)), None)
            if next_h is not None:
                curr = curr.replace(hour=next_h, minute=minutes[0], second=seconds[0])
            else:
                curr = (curr + step_sign * timedelta(days=1)).replace(
                    hour=hours[0], minute=minutes[0], second=seconds[0]
                )
            continue

        if t == "daily":
            curr += step_sign * timedelta(days=1)
            curr = curr.replace(hour=hours[0], minute=minutes[0], second=seconds[0])
            continue

        curr += step_sign * timedelta(days=1)
        curr = curr.replace(hour=hours[0], minute=minutes[0], second=seconds[0])


def compute_target(schedule: dict, now: datetime) -> datetime:
    return _find_target(schedule, now, forward=False)


def compute_next_target(schedule: dict, now: datetime) -> datetime:
    return _find_target(schedule, now, forward=True)


def load_tasks():
    if config.IS_TEST_ENV:
        with TEST_TASK_FILE.open() as f:
            return yaml.safe_load(f)
    task_file = LOCAL_TASK_FILE if LOCAL_TASK_FILE.exists() else DEFAULT_TASK_FILE
    with task_file.open() as f:
        return yaml.safe_load(f) or []


def load_state():
    if STATE_FILE.exists():
        with STATE_FILE.open() as f:
            return {k: datetime.fromisoformat(v) for k, v in json.load(f).items()}
    return {}


def save_state(state):
    serialized = {k: v.isoformat() for k, v in state.items()}
    atomic_write_json(STATE_FILE, serialized)


def get_command_preset_info(command: str) -> dict:
    segments = [s.strip() for s in command.split("&&") if s.strip()]
    if len(segments) == 1:
        try:
            parts = shlex.split(segments[0])
        except ValueError:
            return {"is_preset": False, "flag": None, "name": None}

        if parts and parts[0] == "uv":
            try:
                run_idx = parts.index("run")
            except ValueError:
                run_idx = -1

            if run_idx != -1 and len(parts) > run_idx + 3:
                if parts[run_idx + 1] == "-m" and parts[run_idx + 2] == "obsidian_ai_hub":
                    flag = parts[run_idx + 3]
                    if flag in PRESET_FLAGS:
                        return {"is_preset": True, "flag": flag, "name": PRESET_FLAGS[flag]}
    return {"is_preset": False, "flag": None, "name": None}


def parse_command(command: str) -> list[dict]:
    if not command or not command.strip():
        raise ValueError("Command must not be empty")

    segments = [segment.strip() for segment in command.split("&&")]
    if any(not s for s in segments):
        raise ValueError("Command contains empty segments or trailing '&&'")

    parsed_segments = []
    current_cwd = None

    for segment in segments:
        try:
            parts = shlex.split(segment)
        except ValueError as e:
            raise ValueError(f"shlex parsing error in segment '{segment}': {e}") from e

        if not parts:
            raise ValueError(f"Empty segment after parsing: '{segment}'")

        if parts[0] == "cd":
            if len(parts) != 2:
                raise ValueError(f"Unsupported or invalid 'cd' command: '{segment}'. 'cd' must have exactly one path argument.")
            current_cwd = parts[1]
        else:
            parsed_segments.append({
                "cwd": current_cwd,
                "args": parts
            })

    if not parsed_segments:
        raise ValueError("The command does not contain any executable command segment (only 'cd' commands).")

    return parsed_segments


def validate_tasks(tasks: list) -> None:
    seen_ids = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("Each task must be a dictionary")

        task_id = task.get("id")
        if not task_id or not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("Task ID is required and must be a non-empty string")

        if task_id in seen_ids:
            raise ValueError(f"Duplicate task ID: {task_id}")
        seen_ids.add(task_id)

        enabled = task.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"Task '{task_id}': enabled must be a boolean")

        schedule = task.get("schedule")
        if not isinstance(schedule, dict):
            raise ValueError(f"Task '{task_id}': schedule is required and must be a dictionary")

        try:
            normalize_schedule(schedule)
        except ValueError as e:
            raise ValueError(f"Task '{task_id}': Invalid schedule: {e}")

        command = task.get("command")
        if not command or not isinstance(command, str) or not command.strip():
            raise ValueError(f"Task '{task_id}': Command must be a non-empty string")

        try:
            parse_command(command)
        except ValueError as e:
            raise ValueError(f"Task '{task_id}': Invalid command structure: {e}")


def get_tasks_file_and_revision() -> tuple[Path, str, list]:
    if config.IS_TEST_ENV:
        task_file = TEST_TASK_FILE
    else:
        task_file = LOCAL_TASK_FILE if LOCAL_TASK_FILE.exists() else DEFAULT_TASK_FILE

    if not task_file.exists():
        return task_file, "", []

    with open(task_file, "rb") as f:
        content_bytes = f.read()

    sha = hashlib.sha256(content_bytes).hexdigest()

    try:
        tasks = yaml.safe_load(content_bytes.decode("utf-8")) or []
    except Exception:
        tasks = []

    return task_file, sha, tasks


def get_tasks_file_and_revision_locked() -> tuple[Path, str, list]:
    with acquire_task_config_lock():
        return get_tasks_file_and_revision()


def save_tasks_and_arm(new_tasks: list, old_tasks: list, now: datetime):
    old_by_id = {t["id"]: t for t in old_tasks if "id" in t}
    state = load_state()
    new_ids = {t["id"] for t in new_tasks if "id" in t}

    # 1. Clean up deleted tasks from state
    for old_id in list(state.keys()):
        if old_id not in new_ids:
            state.pop(old_id, None)

    # 2. Check each task for arming
    for task in new_tasks:
        task_id = task.get("id")
        if not task_id:
            continue

        if not task.get("enabled", True):
            continue

        need_arm = False
        if task_id not in old_by_id:
            need_arm = True
        else:
            old_task = old_by_id[task_id]
            if not old_task.get("enabled", True):
                need_arm = True
            old_sched = old_task.get("schedule")
            new_sched = task.get("schedule")
            try:
                if normalize_schedule(old_sched) != normalize_schedule(new_sched):
                    need_arm = True
            except Exception:
                need_arm = True
            if old_task.get("command") != task.get("command"):
                need_arm = True

        if need_arm:
            state[task_id] = now

    # Save
    atomic_write_yaml(LOCAL_TASK_FILE, new_tasks)
    save_state(state)


def run_command(command):
    """Run a scheduled command without invoking a shell.

    Supports the existing task format with optional "cd <path> && ..." chains.
    Each segment is parsed with shlex and executed with shell=False.
    """
    cwd = None
    segments = [
        segment.strip() for segment in str(command).split("&&") if segment.strip()
    ]
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

    # 1. Acquire runner lock
    RUNNER_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    runner_f = open(RUNNER_LOCK_FILE, "w")
    try:
        fcntl.flock(runner_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.info("Another scheduler runner is already running. Exiting.")
        return

    # 2. Under config lock, load snapshot
    with acquire_task_config_lock():
        tasks = load_tasks()

    # 3. Execute
    for task in tasks:
        if not task.get("enabled", True):
            continue

        task_id = task["id"]
        schedule = task["schedule"]
        command = task["command"]

        with acquire_task_config_lock():
            current_state = load_state()
            last_run = current_state.get(task_id, datetime.min)

        target = compute_target(schedule, now)

        if last_run < target <= now:
            logger.info("Running task: %s", task_id)
            run_command(command)

            with acquire_task_config_lock():
                current_state = load_state()
                current_state[task_id] = now
                save_state(current_state)


if __name__ == "__main__":
    main()
