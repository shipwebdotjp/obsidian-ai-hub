"""One-shot Scheduler Jobs: SQLite queue for run-once commands.

Agent registers an arbitrary command via the ``register_one_shot_job`` tool;
the next ``job_runner`` cycle (or once ``run_at`` arrives) claims it and runs
it exactly once (at-most-once). Terminal rows are kept 30 days.
"""

import json
import logging
import shlex
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.scheduler_jobs import recurring

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"
DISPATCHED = "dispatched"

TARGET_COMMAND = "command"
TARGET_WORKFLOW = "workflow"

SOURCE_AGENT = "agent"
SOURCE_MANUAL = "manual"
SOURCES = (SOURCE_AGENT, SOURCE_MANUAL)

TERMINAL_STATUSES = (SUCCEEDED, FAILED, CANCELLED, INTERRUPTED, DISPATCHED)
ALL_STATUSES = (
    QUEUED,
    RUNNING,
    SUCCEEDED,
    FAILED,
    CANCELLED,
    INTERRUPTED,
    DISPATCHED,
)

MAX_OUTPUT_CHARS = 20000
RETENTION_DAYS = 30


def parse_run_at(value: Any, *, now: Optional[datetime] = None) -> Optional[str]:
    """Normalize an arbitrary datetime input to a UTC ISO string.

    ``None``/empty means "already due" (caller stores ``now`` UTC). Naive
    datetimes and timezone-less strings are interpreted as JST; offset-aware
    inputs keep their offset and are converted to UTC. Past datetimes are kept
    as-is so they run on the next cycle.
    """
    ref = now or datetime.now(timezone.utc)
    if value is None or (isinstance(value, str) and not value.strip()):
        return ref.astimezone(timezone.utc).isoformat()

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as e:
            raise ValueError(f"Invalid run_at datetime: {value}") from e
    else:
        raise ValueError(f"Invalid run_at datetime: {value!r}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(timezone.utc).isoformat()


def _normalize_source(source: str, source_job_id: Optional[str]) -> tuple[str, Optional[str]]:
    if source not in SOURCES:
        raise ValueError(f"Invalid source: {source!r}")
    if source_job_id is None:
        if source == SOURCE_MANUAL:
            # Without source_job_id the partial unique index cannot dedupe, so
            # a manual run must always identify its recurring job.
            raise ValueError("source_job_id is required for a manual run")
        return source, None
    if source != SOURCE_MANUAL:
        # Non-null source_job_id always means "manual run of this recurring
        # job"; keeping agent rows clean makes that invariant enforceable.
        raise ValueError("source_job_id is only valid for a manual run")
    if not isinstance(source_job_id, str) or not source_job_id.strip():
        raise ValueError("source_job_id must be a non-empty string when provided")
    return source, source_job_id.strip()


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["segments"] = json.loads(d.get("segments_json") or "[]")
    except (ValueError, TypeError):
        d["segments"] = []
    d.pop("segments_json", None)
    try:
        d["inputs"] = json.loads(d.get("inputs_json") or "{}")
    except (ValueError, TypeError):
        d["inputs"] = {}
    d.pop("inputs_json", None)
    d["target_kind"] = d.get("target_kind") or TARGET_COMMAND
    d["source"] = d.get("source") or SOURCE_AGENT
    d["output_truncated"] = bool(d.get("output_truncated"))
    return d


def register_one_shot_job(
    command: str,
    run_at: Any = None,
    *,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
    source: str = SOURCE_AGENT,
    source_job_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Validate and persist a one-shot job as ``queued``. No shell is used.

    ``source='manual'`` with ``source_job_id`` records a Web UI "run now" that
    copied a recurring job's target; the partial unique index rejects a second
    queued/running manual row for the same recurring job (``IntegrityError``).
    """
    if not command or not isinstance(command, str) or not command.strip():
        raise ValueError("Command must be a non-empty string")
    try:
        recurring.parse_command(command)
    except ValueError as e:
        raise ValueError(f"Invalid command structure: {e}") from e

    source, source_job_id = _normalize_source(source, source_job_id)

    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    run_at_utc = parse_run_at(run_at, now=ref)
    created_at = ref.astimezone(timezone.utc).isoformat()
    job_id = uuid.uuid4().hex

    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO one_shot_jobs (
                job_id, command, run_at_utc, status,
                agent_id, session_id, run_id,
                source, source_job_id,
                created_at, started_at, finished_at,
                exit_code, segments_json, output_truncated, error_summary
            ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, '[]', 0, NULL)
            """,
            (
                job_id,
                command,
                run_at_utc,
                agent_id,
                session_id,
                run_id,
                source,
                source_job_id,
                created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    result = get_one_shot_job(job_id)
    if result is None:
        raise RuntimeError(f"Failed to persist one-shot job {job_id}")
    return result


def register_one_shot_workflow_job(
    workflow_id: str,
    inputs: Optional[dict[str, Any]] = None,
    run_at: Any = None,
    *,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
    source: str = SOURCE_AGENT,
    source_job_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Register a one-shot job that starts a published Workflow.

    The target is validated against the current published Revision so a bad
    registration is rejected up front. At execution the latest published
    Revision is re-resolved (it may have changed). Success records
    ``status='dispatched'`` and the created Workflow Run; the Workflow's own
    outcome is tracked on the Run, not here.
    """
    target = recurring.validate_workflow_target(workflow_id, inputs)
    source, source_job_id = _normalize_source(source, source_job_id)

    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    run_at_utc = parse_run_at(run_at, now=ref)
    created_at = ref.astimezone(timezone.utc).isoformat()
    job_id = uuid.uuid4().hex

    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO one_shot_jobs (
                job_id, target_kind, command, workflow_id, inputs_json,
                workflow_run_id, run_at_utc, status, agent_id, session_id,
                run_id, source, source_job_id,
                created_at, started_at, finished_at,
                exit_code, segments_json, output_truncated, error_summary
            ) VALUES (?, 'workflow', NULL, ?, ?, NULL, ?, 'queued', ?, ?, ?, ?, ?,
                      ?, NULL, NULL, NULL, '[]', 0, NULL)
            """,
            (
                job_id,
                target["workflow_id"],
                json.dumps(target["inputs"], ensure_ascii=False),
                run_at_utc,
                agent_id,
                session_id,
                run_id,
                source,
                source_job_id,
                created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    result = get_one_shot_job(job_id)
    if result is None:
        raise RuntimeError(f"Failed to persist one-shot workflow job {job_id}")
    return result


def get_one_shot_job(job_id: str) -> Optional[dict]:
    conn = get_db_connection()
    try:
        cur = conn.execute("SELECT * FROM one_shot_jobs WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def find_active_manual_run(source_job_id: str) -> Optional[dict]:
    """Return the queued/running manual run for a recurring job, else None.

    Used as the Web UI's pre-check; the partial unique index is the race-safe
    backstop for concurrent requests and web-vs-runner timing.
    """
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM one_shot_jobs WHERE source = ? AND source_job_id = ?"
            " AND status IN ('queued','running') ORDER BY created_at ASC LIMIT 1",
            (SOURCE_MANUAL, source_job_id),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_one_shot_jobs(limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
    """Return unfinished jobs first, then terminal history."""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    conn = get_db_connection()
    try:
        total = conn.execute("SELECT COUNT(*) AS n FROM one_shot_jobs").fetchone()["n"]
        pending = [
            _row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM one_shot_jobs WHERE status IN ('queued','running')"
                " ORDER BY run_at_utc ASC, created_at ASC"
            ).fetchall()
        ]
        history = [
            _row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM one_shot_jobs WHERE status NOT IN ('queued','running')"
                " ORDER BY finished_at DESC, created_at DESC"
            ).fetchall()
        ]
        combined = pending + history
        return combined[offset : offset + limit], total
    finally:
        conn.close()


def find_non_terminal_workflow_jobs(workflow_id: str) -> list[dict]:
    """Return non-terminal one-shot jobs targeting ``workflow_id``.

    A targeted query instead of the capped job listing, so a workflow is
    never deleted while any pending job still references it.
    """
    placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM one_shot_jobs WHERE target_kind = ? "
            f"AND workflow_id = ? AND status NOT IN ({placeholders})"
            " ORDER BY created_at ASC",
            (TARGET_WORKFLOW, workflow_id, *TERMINAL_STATUSES),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def cancel_one_shot_job(job_id: str, *, now: Optional[datetime] = None) -> dict:
    """Cancel a ``queued`` job. Running or terminal jobs cannot be cancelled."""
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    finished_at = ref.astimezone(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        cur = conn.execute("SELECT status FROM one_shot_jobs WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"One-shot job not found: {job_id}")
        if row["status"] != QUEUED:
            raise ValueError(f"Only queued jobs can be cancelled (status={row['status']})")
        # Re-check rowcount: the runner may claim the job between the SELECT
        # above and this UPDATE (web cancel vs runner process). A lost race
        # must report failure, never a phantom cancellation of a running job.
        cur = conn.execute(
            "UPDATE one_shot_jobs SET status='cancelled', finished_at=? WHERE job_id=? AND status='queued'",
            (finished_at, job_id),
        )
        if cur.rowcount != 1:
            raise ValueError(f"Only queued jobs can be cancelled (job_id={job_id})")
        conn.commit()
    finally:
        conn.close()
    result = get_one_shot_job(job_id)
    if result is None:
        raise LookupError(f"One-shot job not found: {job_id}")
    return result


def prune_expired_one_shot_jobs(
    days: int = RETENTION_DAYS, *, now: Optional[datetime] = None
) -> int:
    """Delete terminal jobs whose ``finished_at`` is older than ``days``."""
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    cutoff = (ref.astimezone(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_db_connection()
    try:
        placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
        cur = conn.execute(
            f"DELETE FROM one_shot_jobs WHERE status IN ({placeholders})"
            " AND finished_at IS NOT NULL AND finished_at < ?",
            (*TERMINAL_STATUSES, cutoff),
        )
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


def mark_interrupted_orphans(*, now: Optional[datetime] = None) -> int:
    """Mark leftover ``running`` rows as ``interrupted`` (crash recovery).

    Runs inside the runner lock at startup. Interrupted jobs are never
    re-executed automatically (at-most-once).
    """
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    finished_at = ref.astimezone(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "UPDATE one_shot_jobs SET status='interrupted', finished_at=?,"
            " error_summary='Runner restarted while job was running; not retried (at-most-once).'"
            " WHERE status='running'",
            (finished_at,),
        )
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


def claim_due_jobs(*, now: Optional[datetime] = None, limit: int = 50) -> list[dict]:
    """Atomically claim due ``queued`` jobs as ``running``."""
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    now_utc = ref.astimezone(timezone.utc).isoformat()
    started_at = now_utc
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT job_id FROM one_shot_jobs WHERE status='queued' AND run_at_utc <= ?"
            " ORDER BY run_at_utc ASC, created_at ASC LIMIT ?",
            (now_utc, max(1, int(limit))),
        ).fetchall()
        claimed: list[dict] = []
        for r in rows:
            cur = conn.execute(
                "UPDATE one_shot_jobs SET status='running', started_at=?"
                " WHERE job_id=? AND status='queued'",
                (started_at, r["job_id"]),
            )
            if cur.rowcount == 1:
                row = conn.execute(
                    "SELECT * FROM one_shot_jobs WHERE job_id = ?", (r["job_id"],)
                ).fetchone()
                if row is not None:
                    claimed.append(_row_to_dict(row))
        conn.commit()
        return claimed
    finally:
        conn.close()


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + f"\n...[truncated {len(text) - MAX_OUTPUT_CHARS} chars]", True
    return text, False


def _default_executor(args: list[str], cwd: Optional[str]):
    return subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)


def execute_claimed_job(
    job: dict,
    *,
    executor: Optional[Callable[..., Any]] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Execute a claimed (``running``) job and persist the terminal state."""
    run = executor or _default_executor
    job_id = job["job_id"]
    command = job["command"]
    segments = recurring.parse_command(command)

    segment_results: list[dict] = []
    overall_exit = 0
    output_truncated = False
    error_summary: Optional[str] = None

    try:
        for seg in segments:
            try:
                proc = run(seg["args"], seg.get("cwd"))
                exit_code = int(getattr(proc, "returncode", 0) or 0)
                stdout = str(getattr(proc, "stdout", "") or "")
                stderr = str(getattr(proc, "stderr", "") or "")
            except Exception as exc:
                exit_code = 127
                stdout, stderr = "", f"{type(exc).__name__}: {exc}"
                error_summary = f"Failed to start segment: {exc}"
            stdout, trunc_out = _truncate(stdout)
            stderr, trunc_err = _truncate(stderr)
            output_truncated = output_truncated or trunc_out or trunc_err
            segment_results.append(
                {
                    "cwd": seg.get("cwd"),
                    "args": seg["args"],
                    "exit_code": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "truncated_stdout": trunc_out,
                    "truncated_stderr": trunc_err,
                }
            )
            if exit_code != 0:
                overall_exit = exit_code
                if error_summary is None:
                    error_summary = f"Segment exited with code {exit_code}: {shlex.join(seg['args'])}"
                break
    except Exception as exc:
        overall_exit = 127
        error_summary = f"{type(exc).__name__}: {exc}"
        logger.exception("One-shot job %s execution failed", job_id)

    status = SUCCEEDED if overall_exit == 0 else FAILED
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    finished_at = ref.astimezone(timezone.utc).isoformat()

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE one_shot_jobs SET status=?, finished_at=?, exit_code=?,"
            " segments_json=?, output_truncated=?, error_summary=? WHERE job_id=?",
            (
                status,
                finished_at,
                overall_exit,
                json.dumps(segment_results, ensure_ascii=False),
                1 if output_truncated else 0,
                error_summary,
                job_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    result = get_one_shot_job(job_id)
    if result is None:
        raise LookupError(f"One-shot job not found: {job_id}")
    return result


def dispatch_claimed_workflow_job(
    job: dict, *, now: Optional[datetime] = None
) -> dict:
    """Start a Workflow Run for a claimed (``running``) workflow one-shot job.

    The Run insert and the terminal status update commit together: a crash
    before the commit leaves the row ``running`` (later marked ``interrupted``
    with no Run), and a crash after it leaves ``dispatched`` with the Run. A
    duplicate Run is impossible because the row is only dispatched once.
    """
    from obsidian_ai_hub.workflow import scheduling
    from obsidian_ai_hub.workflow import store as workflow_store

    job_id = job["job_id"]
    workflow_id = job["workflow_id"]
    inputs = job.get("inputs") or {}

    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    finished_at = ref.astimezone(timezone.utc).isoformat()

    conn = get_db_connection()
    try:
        with conn:
            try:
                run, _revision_id, _ = scheduling.create_run_for_latest_published(
                    conn,
                    workflow_id,
                    inputs,
                    reference_time=job.get("run_at_utc") or finished_at,
                )
            except scheduling.WorkflowDispatchError as exc:
                conn.execute(
                    "UPDATE one_shot_jobs SET status='failed', finished_at=?,"
                    " error_summary=? WHERE job_id=? AND status='running'",
                    (finished_at, str(exc), job_id),
                )
            else:
                workflow_store.append_event(
                    str(run["run_id"]),
                    "run_scheduled",
                    {
                        "source_kind": scheduling.SOURCE_ONE_SHOT,
                        "scheduler_job_id": job_id,
                    },
                    conn=conn,
                )
                conn.execute(
                    "UPDATE one_shot_jobs SET status='dispatched',"
                    " workflow_run_id=?, finished_at=?, error_summary=NULL"
                    " WHERE job_id=? AND status='running'",
                    (run["run_id"], finished_at, job_id),
                )
    finally:
        conn.close()
    result = get_one_shot_job(job_id)
    if result is None:
        raise LookupError(f"One-shot job not found: {job_id}")
    return result


def run_due_one_shot_jobs(
    *,
    executor: Optional[Callable[..., Any]] = None,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> list[dict]:
    """Claim due jobs and execute each exactly once. Returns terminal rows."""
    claimed = claim_due_jobs(now=now, limit=limit)
    results: list[dict] = []
    for job in claimed:
        # Isolate each job: one unexpected failure must not abort the batch and
        # leave later claimed rows with no terminal status (startup recovery
        # would then mark them ``interrupted`` and drop the work).
        try:
            if job.get("target_kind") == TARGET_WORKFLOW:
                results.append(dispatch_claimed_workflow_job(job, now=now))
            else:
                results.append(execute_claimed_job(job, executor=executor, now=now))
        except Exception:
            logger.exception("One-shot job %s failed to process", job.get("job_id"))
    return results
