"""Recurring Scheduler Jobs: YAML-defined, schedule-driven execution.

This module is the renamed successor of the former ``task_runner`` scheduler
Task code. Scheduler Job (recurring / one-shot) is a separate aggregate from
the Task Agent Task and uses ``jobs/`` YAML, ``jobs/last_run.json`` state,
``.job-config.lock`` / ``.job-runner.lock`` files, and the ``job_state`` table.
"""

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

TEST_JOB_FILE = config.BASE_DIR / "jobs" / "jobs.test.yml"
DEFAULT_JOB_FILE = config.BASE_DIR / "jobs" / "jobs.yml"
LOCAL_JOB_FILE = config.BASE_DIR / "jobs" / "jobs.local.yml"
STATE_FILE = config.JOB_RUN_STATE_PATH

LOCK_FILE = STATE_FILE.parent / ".job-config.lock"
RUNNER_LOCK_FILE = STATE_FILE.parent / ".job-runner.lock"

# YAML field recording which Agent registered a recurring job. It is written
# only by ``register_recurring_job`` (never by the human-facing API) and grants
# that Agent enable/disable rights until a human edits the job.
AGENT_SOURCE_FIELD = "agent_source"
_AGENT_SOURCE_OPTIONAL_FIELDS = ("session_id", "run_id", "registered_at")


# Legacy Scheduler Task paths. The runner never reads these; their presence
# means YAML migration has not run, so startup fails closed with guidance.
LEGACY_TASK_DIR = config.BASE_DIR / "tasks"
LEGACY_TASK_FILES = (
    LEGACY_TASK_DIR / "tasks.local.yml",
    LEGACY_TASK_DIR / "tasks.yml",
    LEGACY_TASK_DIR / "tasks.test.yml",
    LEGACY_TASK_DIR / "last_run.json",
)
LEGACY_STATE_FILE = LEGACY_TASK_DIR / "last_run.json"
LEGACY_KNOWLEDGE_STATE_FILE = LEGACY_TASK_DIR / "knowledge_sync_state.json"

MIGRATION_GUIDANCE = (
    "Legacy Scheduler Task files found in tasks/. "
    "Run YAML migration first: "
    "python -m obsidian_ai_hub.job_runner --migrate-tasks-to-jobs "
    "(moves tasks/tasks.local.yml or tasks/tasks.yml to jobs/jobs.local.yml, "
    "copies last_run.json state, then removes legacy files)."
)

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
    "--generate-planner-proposals": "AIプランナー提案生成",
    "--log-activity": "Activity log",
    "--hitl-dispatch": "HITL dispatch",
    "--cleanup-line-webhooks": "LINE Webhook cleanup",
}


def assert_no_legacy_task_files() -> None:
    """Fail closed when unmigrated Scheduler Task files remain.

    The runner reads ``jobs/`` only and never merges both directories, so a
    leftover legacy file means the operator may be editing a file that has no
    effect. Raise instead of silently ignoring it. Skipped in test envs where
    the sandbox redirects all writable paths (fail-closed is covered by
    dedicated tests with patched legacy paths).
    """
    if config.IS_TEST_ENV:
        return
    leftovers = [p for p in LEGACY_TASK_FILES if p.exists()]
    if leftovers:
        names = ", ".join(p.name for p in leftovers)
        raise RuntimeError(f"{MIGRATION_GUIDANCE} Found: {names}")


@contextlib.contextmanager
def acquire_job_config_lock():
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

    from datetime import timedelta

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


def load_jobs():
    assert_no_legacy_task_files()
    if config.IS_TEST_ENV:
        if not TEST_JOB_FILE.exists():
            return []
        with TEST_JOB_FILE.open() as f:
            return yaml.safe_load(f)
    job_file = LOCAL_JOB_FILE if LOCAL_JOB_FILE.exists() else DEFAULT_JOB_FILE
    if not job_file.exists():
        return []
    with job_file.open() as f:
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


def validate_jobs(jobs: list) -> None:
    seen_ids = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("Each job must be a dictionary")

        job_id = job.get("id")
        if not job_id or not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("Job ID is required and must be a non-empty string")

        if job_id in seen_ids:
            raise ValueError(f"Duplicate job ID: {job_id}")
        seen_ids.add(job_id)

        enabled = job.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"Job '{job_id}': enabled must be a boolean")

        schedule = job.get("schedule")
        if not isinstance(schedule, dict):
            raise ValueError(f"Job '{job_id}': schedule is required and must be a dictionary")

        try:
            normalize_schedule(schedule)
        except ValueError as e:
            raise ValueError(f"Job '{job_id}': Invalid schedule: {e}")

        command = job.get("command")
        if not command or not isinstance(command, str) or not command.strip():
            raise ValueError(f"Job '{job_id}': Command must be a non-empty string")

        try:
            parse_command(command)
        except ValueError as e:
            raise ValueError(f"Job '{job_id}': Invalid command structure: {e}")


def get_jobs_file_and_revision() -> tuple[Path, str, list]:
    assert_no_legacy_task_files()
    if config.IS_TEST_ENV:
        job_file = TEST_JOB_FILE
    else:
        job_file = LOCAL_JOB_FILE if LOCAL_JOB_FILE.exists() else DEFAULT_JOB_FILE

    if not job_file.exists():
        return job_file, "", []

    with open(job_file, "rb") as f:
        content_bytes = f.read()

    sha = hashlib.sha256(content_bytes).hexdigest()

    # Corrupt YAML must surface (500 via the API, loud failure in the runner),
    # never silently read as empty: the save flow would otherwise overwrite the
    # corrupt file with old_jobs=[] and lose data.
    jobs = yaml.safe_load(content_bytes.decode("utf-8")) or []

    return job_file, sha, jobs


def get_jobs_file_and_revision_locked() -> tuple[Path, str, list]:
    with acquire_job_config_lock():
        return get_jobs_file_and_revision()


def save_jobs_and_arm(new_jobs: list, old_jobs: list, now: datetime):
    old_by_id = {t["id"]: t for t in old_jobs if "id" in t}
    state = load_state()
    new_ids = {t["id"] for t in new_jobs if "id" in t}

    # 1. Clean up deleted jobs from state
    for old_id in list(state.keys()):
        if old_id not in new_ids:
            state.pop(old_id, None)

    # 2. Check each job for arming
    for job in new_jobs:
        job_id = job.get("id")
        if not job_id:
            continue

        if not job.get("enabled", True):
            continue

        need_arm = False
        if job_id not in old_by_id:
            need_arm = True
        else:
            old_job = old_by_id[job_id]
            if not old_job.get("enabled", True):
                need_arm = True
            old_sched = old_job.get("schedule")
            new_sched = job.get("schedule")
            try:
                if normalize_schedule(old_sched) != normalize_schedule(new_sched):
                    need_arm = True
            except Exception:
                need_arm = True
            if old_job.get("command") != job.get("command"):
                need_arm = True

        if need_arm:
            state[job_id] = now

    # Save
    atomic_write_yaml(LOCAL_JOB_FILE, new_jobs)
    save_state(state)


def get_agent_source(job) -> Optional[dict]:
    """Return a sanitized ``agent_source`` dict, else ``None``.

    A missing, non-dict, or ``agent_id``-less source is treated as "no owner"
    so corrupt hand-edited YAML never breaks the runner or the /jobs list; it
    simply cannot be toggled by an Agent. Optional fields with a wrong type are
    also rejected here so the value always matches the API response schema.
    """
    if not isinstance(job, dict):
        return None
    source = job.get(AGENT_SOURCE_FIELD)
    if not isinstance(source, dict):
        return None
    agent_id = source.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        return None
    sanitized = {"agent_id": agent_id}
    for key in _AGENT_SOURCE_OPTIONAL_FIELDS:
        value = source.get(key)
        if value is None or isinstance(value, str):
            sanitized[key] = value
        else:
            return None
    return sanitized


def is_agent_owned_by(job, agent_id: Optional[str]) -> bool:
    if not agent_id:
        return False
    source = get_agent_source(job)
    return source is not None and source.get("agent_id") == agent_id


def _find_job_index(jobs: list, job_id: str) -> int:
    for index, job in enumerate(jobs or []):
        if isinstance(job, dict) and job.get("id") == job_id:
            return index
    return -1


def _validate_job_id(job_id) -> str:
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("Job ID is required and must be a non-empty string")
    return job_id


def _utc_timestamp(now: Optional[datetime]) -> str:
    # ``now`` is usually a naive local time (matching arming/last_run state), so
    # a naive value is interpreted as local and converted; the default is read
    # as aware UTC. Either way ``registered_at`` is a true UTC instant.
    ref = now if now is not None else datetime.now(timezone.utc)
    return ref.astimezone(timezone.utc).isoformat()


def register_recurring_job(
    job_id: str,
    command: str,
    schedule: dict,
    *,
    agent_id: Optional[str],
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Register a new enabled recurring job owned by ``agent_id``.

    The full active YAML is read, the new entry is appended, and the entire
    list is written atomically to ``jobs/jobs.local.yml`` so existing jobs and
    ``last_run`` state are never lost. Arming follows ``save_jobs_and_arm``:
    the new job is armed to ``now`` and runs from its next matching slot, not
    retroactively. Raises ``ValueError`` without changing anything when the
    trusted agent identity is missing, the schedule/command is invalid, or the
    job ID already exists.
    """
    agent_id = str(agent_id).strip() if agent_id else ""
    if not agent_id:
        raise ValueError("trusted agent identity is required to register a recurring job")
    _validate_job_id(job_id)
    try:
        normalize_schedule(schedule)
    except ValueError as e:
        raise ValueError(f"Invalid schedule: {e}") from e
    try:
        parse_command(command)
    except ValueError as e:
        raise ValueError(f"Invalid command structure: {e}") from e

    arm_now = now or datetime.now()

    with acquire_job_config_lock():
        _, _, old_jobs = get_jobs_file_and_revision()
        if _find_job_index(old_jobs, job_id) != -1:
            raise ValueError(f"Job ID already exists: {job_id}")

        source: dict = {
            "agent_id": agent_id,
            "session_id": str(session_id) if session_id else None,
            "run_id": str(run_id) if run_id else None,
            "registered_at": _utc_timestamp(arm_now),
        }
        new_job = {
            "id": job_id,
            "enabled": True,
            "schedule": schedule,
            "command": command,
            AGENT_SOURCE_FIELD: source,
        }
        new_jobs = list(old_jobs or []) + [new_job]
        validate_jobs(new_jobs)
        save_jobs_and_arm(new_jobs, old_jobs, arm_now)
        _, revision, _ = get_jobs_file_and_revision()

    return {
        "job_id": job_id,
        "enabled": True,
        "next_run": compute_next_target(schedule, arm_now).isoformat(),
        "revision": revision,
    }


def set_recurring_job_enabled(
    job_id: str,
    enabled: bool,
    *,
    agent_id: Optional[str],
    now: Optional[datetime] = None,
) -> dict:
    """Enable/disable a job only when ``agent_id`` registered it.

    The active YAML is read, the single matching entry is replaced, and the
    full list is written atomically. Only a disabled→enabled transition
    re-arms the job (via ``save_jobs_and_arm``). Missing IDs, manual jobs, and
    jobs owned by another Agent fail with ``ValueError`` and no change.
    """
    agent_id = str(agent_id).strip() if agent_id else ""
    if not agent_id:
        raise ValueError("trusted agent identity is required to change a recurring job")
    _validate_job_id(job_id)
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")

    arm_now = now or datetime.now()

    with acquire_job_config_lock():
        _, _, old_jobs = get_jobs_file_and_revision()
        index = _find_job_index(old_jobs, job_id)
        if index == -1:
            raise ValueError(f"Recurring job not found: {job_id}")
        if not is_agent_owned_by(old_jobs[index], agent_id):
            raise ValueError(
                f"Recurring job '{job_id}' is not owned by this agent; "
                "only the registering agent may change it"
            )

        new_jobs = list(old_jobs)
        updated = dict(new_jobs[index])
        updated["enabled"] = enabled
        new_jobs[index] = updated

        validate_jobs(new_jobs)
        save_jobs_and_arm(new_jobs, old_jobs, arm_now)
        _, revision, _ = get_jobs_file_and_revision()
        schedule = updated.get("schedule")

    next_run = None
    if enabled:
        try:
            next_run = compute_next_target(schedule, arm_now).isoformat()
        except Exception:
            next_run = None

    return {
        "job_id": job_id,
        "enabled": enabled,
        "next_run": next_run,
        "revision": revision,
    }


def _job_meaning_changed(old: dict, new: dict) -> bool:
    """True when a human PUT changes the identity/schedule/command/enabled.

    Reordering and same-value PUTs keep the entry's metadata (including
    ``agent_source``). Schedule comparison is semantic so equivalent cron
    spellings do not count as a change.
    """
    if old.get("command") != new.get("command"):
        return True
    if bool(old.get("enabled", True)) != bool(new.get("enabled", True)):
        return True
    try:
        if normalize_schedule(old.get("schedule")) != normalize_schedule(new.get("schedule")):
            return True
    except Exception:
        return True
    return False


def merge_recurring_jobs(current_jobs: list, incoming_jobs: list) -> list:
    """Merge a human full-list PUT onto the current raw YAML.

    Existing IDs keep their unknown metadata (and ``agent_source`` unless the
    entry was meaningfully changed); ``agent_source`` supplied by the client
    is always ignored so ownership can only be created by Agent registration.
    New entries keep their other fields but a client-supplied ``agent_source``
    is stripped. Result order follows ``incoming_jobs``; omitted IDs are
    deleted.
    """
    current_by_id = {
        job["id"]: job
        for job in (current_jobs or [])
        if isinstance(job, dict) and isinstance(job.get("id"), str)
    }
    merged_jobs: list = []
    for incoming in incoming_jobs or []:
        if not isinstance(incoming, dict):
            raise ValueError("Each job must be a dictionary")
        job_id = incoming.get("id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("Job ID is required and must be a non-empty string")

        if job_id in current_by_id:
            base = dict(current_by_id[job_id])
            changed = _job_meaning_changed(base, incoming)
            for key in ("enabled", "schedule", "command"):
                if key in incoming:
                    base[key] = incoming[key]
            base["id"] = job_id
            if changed:
                base.pop(AGENT_SOURCE_FIELD, None)
            merged_jobs.append(base)
        else:
            entry = dict(incoming)
            entry.pop(AGENT_SOURCE_FIELD, None)
            entry["id"] = job_id
            merged_jobs.append(entry)
    return merged_jobs


def run_command(command):
    """Run a scheduled command without invoking a shell.

    Supports the existing job format with optional "cd <path> && ..." chains.
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


def migrate_tasks_yaml_to_jobs(base_dir: Optional[Path] = None) -> Path:
    """One-shot YAML migration: tasks/ -> jobs/.

    Copies ``tasks/tasks.local.yml`` (fallback ``tasks/tasks.yml``) to
    ``jobs/jobs.local.yml`` after validation, copies ``last_run.json`` and
    ``knowledge_sync_state.json`` state files when present, then removes the
    legacy files. Stops without merging when the destination already exists or
    when no legacy source exists.
    """
    root = Path(base_dir) if base_dir is not None else config.BASE_DIR
    legacy_dir = root / "tasks"
    jobs_dir = root / "jobs"
    dest = jobs_dir / "jobs.local.yml"

    if dest.exists():
        raise RuntimeError(
            "Migration stopped: jobs/jobs.local.yml already exists. "
            "Remove it or finish migration manually; refusing to merge both directories."
        )

    legacy_local = legacy_dir / "tasks.local.yml"
    legacy_default = legacy_dir / "tasks.yml"
    source = legacy_local if legacy_local.exists() else legacy_default
    if not source.exists():
        raise RuntimeError(
            "Migration stopped: no legacy tasks YAML found "
            "(tasks/tasks.local.yml or tasks/tasks.yml)."
        )

    with source.open(encoding="utf-8") as f:
        jobs = yaml.safe_load(f) or []
    validate_jobs(jobs)

    jobs_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(dest, jobs)

    new_state = jobs_dir / "last_run.json"
    old_state = legacy_dir / "last_run.json"
    if old_state.exists() and not new_state.exists():
        shutil.copy2(old_state, new_state)

    new_knowledge = jobs_dir / "knowledge_sync_state.json"
    old_knowledge = legacy_dir / "knowledge_sync_state.json"
    if old_knowledge.exists() and not new_knowledge.exists():
        shutil.copy2(old_knowledge, new_knowledge)

    for legacy_file in (
        legacy_dir / "tasks.local.yml",
        legacy_dir / "tasks.yml",
        legacy_dir / "tasks.local.sample.yml",
        legacy_dir / "tasks.test.yml",
        legacy_dir / "last_run.json",
        legacy_dir / "knowledge_sync_state.json",
    ):
        try:
            if legacy_file.exists():
                legacy_file.unlink()
        except OSError:
            logger.warning("Failed to remove legacy file %s", legacy_file)

    # Remove the legacy lock files if present; the runner uses job locks now.
    for legacy_lock in (legacy_dir / ".task-config.lock", legacy_dir / ".task-runner.lock"):
        try:
            if legacy_lock.exists():
                legacy_lock.unlink()
        except OSError:
            logger.warning("Failed to remove legacy lock %s", legacy_lock)

    try:
        if legacy_dir.exists() and not any(legacy_dir.iterdir()):
            legacy_dir.rmdir()
    except OSError:
        logger.warning("Failed to remove legacy tasks directory %s", legacy_dir)

    return dest
