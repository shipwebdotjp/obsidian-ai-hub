"""Task Agent store: tasks, versioned plans, append-only events (SQLite)."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Generator, Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.tasks.redaction import redact_text

logger = logging.getLogger(__name__)


TASK_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

TASK_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"planning", "cancelled"}),
    "planning": frozenset(
        {
            "waiting_user",
            "waiting_approval",
            "running",
            "failed",
            "cancelled",
            "interrupted",
        }
    ),
    "waiting_user": frozenset({"queued", "cancelled"}),
    "waiting_approval": frozenset({"ready", "queued", "cancelled"}),
    "ready": frozenset({"running", "cancelled", "interrupted"}),
    "running": frozenset(
        {"completed", "failed", "waiting_reapproval", "cancelling", "interrupted"}
    ),
    "waiting_reapproval": frozenset({"ready", "queued", "cancelled"}),
    "cancelling": frozenset({"cancelled", "failed", "interrupted"}),
    "interrupted": frozenset({"queued", "cancelled"}),
}

PLAN_STATUSES: frozenset[str] = frozenset(
    {"pending", "approved", "rejected", "superseded"}
)

TASK_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "status_changed",
        "plan_created",
        "plan_approved",
        "plan_rejected",
        "child_run_started",
        "child_run_finished",
        "hitl_question_asked",
        "hitl_question_answered",
        "capability_completed",
        "note",
    }
)


@contextmanager
def auto_connection(
    conn: Optional[sqlite3.Connection] = None,
) -> Generator[tuple[sqlite3.Connection, bool], None, None]:
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True
    try:
        yield conn, close_conn
    finally:
        if close_conn:
            conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_task_transition(from_status: str, to_status: str) -> None:
    allowed = TASK_ALLOWED_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise ValueError(f"Illegal task transition: '{from_status}' -> '{to_status}'.")


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "prompt_text": row["prompt_text"],
        "status": row["status"],
        "current_plan_id": row["current_plan_id"],
        "worker_instance_id": row["worker_instance_id"],
        "active_child_kind": row["active_child_kind"],
        "active_child_run_id": row["active_child_run_id"],
        "result_summary": row["result_summary"],
        "error_summary": row["error_summary"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def _row_to_plan(row: sqlite3.Row) -> dict[str, Any]:
    try:
        plan = json.loads(row["plan_json"]) if row["plan_json"] else {}
    except (json.JSONDecodeError, TypeError):
        plan = {}
    try:
        snapshot = (
            json.loads(row["approval_policy_snapshot"])
            if row["approval_policy_snapshot"]
            else {}
        )
    except (json.JSONDecodeError, TypeError):
        snapshot = {}
    return {
        "plan_id": row["plan_id"],
        "task_id": row["task_id"],
        "version": row["version"],
        "plan": plan,
        "approval_policy_snapshot": snapshot,
        "status": row["status"],
        "rejection_reason": row["rejection_reason"],
        "created_at": row["created_at"],
        "decided_at": row["decided_at"],
    }


def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
    except (json.JSONDecodeError, TypeError):
        payload = {}
    return {
        "event_id": row["event_id"],
        "task_id": row["task_id"],
        "seq": row["seq"],
        "event_type": row["event_type"],
        "payload": payload,
        "created_at": row["created_at"],
    }


def _row_to_capability(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "capability_key": row["capability_key"],
        "adapter_kind": row["adapter_kind"],
        "enabled": bool(row["enabled"]),
        "approval_policy": row["approval_policy"],
        "updated_at": row["updated_at"],
    }


def create_task(
    prompt_text: str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any]:
    """Create a task in ``queued`` status. Blank prompts are rejected."""
    if not prompt_text or not prompt_text.strip():
        raise ValueError("prompt_text must not be blank.")
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            active_conn.execute(
                "INSERT INTO task_agent_tasks (task_id, prompt_text, status, created_at, updated_at) "
                "VALUES (?, ?, 'queued', ?, ?);",
                (task_id, redact_text(prompt_text), now, now),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
        task = get_task(task_id, conn=active_conn)
    if task is None:
        raise FileNotFoundError(f"Task '{task_id}' not found after creation.")
    return task


def get_task(
    task_id: str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any] | None:
    with auto_connection(conn) as (active_conn, _):
        cur = active_conn.execute(
            "SELECT * FROM task_agent_tasks WHERE task_id = ?;", (task_id,)
        )
        row = cur.fetchone()
        return _row_to_task(row) if row is not None else None


def list_tasks(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        if status is not None:
            cur = active_conn.execute(
                "SELECT * FROM task_agent_tasks WHERE status = ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?;",
                (status, limit, offset),
            )
        else:
            cur = active_conn.execute(
                "SELECT * FROM task_agent_tasks ORDER BY created_at DESC LIMIT ? OFFSET ?;",
                (limit, offset),
            )
        return [_row_to_task(row) for row in cur.fetchall()]


def count_tasks(
    status: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    with auto_connection(conn) as (active_conn, _):
        if status is not None:
            cur = active_conn.execute(
                "SELECT COUNT(*) AS total FROM task_agent_tasks WHERE status = ?;",
                (status,),
            )
        else:
            cur = active_conn.execute("SELECT COUNT(*) AS total FROM task_agent_tasks;")
        return int(cur.fetchone()["total"])


def create_plan(
    task_id: str,
    plan: dict[str, Any],
    approval_policy_snapshot: dict[str, Any],
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Save a new plan version for a task and supersede its pending plans."""
    with auto_connection(conn) as (active_conn, is_generated):
        task = get_task(task_id, conn=active_conn)
        if task is None:
            raise FileNotFoundError(f"Task '{task_id}' not found.")
        cur = active_conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_version FROM task_agent_plans "
            "WHERE task_id = ?;",
            (task_id,),
        )
        version = int(cur.fetchone()["max_version"]) + 1
        plan_id = f"tplan_{uuid.uuid4().hex[:12]}"
        now = _now_iso()
        plan_json = redact_text(json.dumps(plan, ensure_ascii=False))

        def _do() -> None:
            active_conn.execute(
                "UPDATE task_agent_plans SET status = 'superseded' "
                "WHERE task_id = ? AND status = 'pending';",
                (task_id,),
            )
            active_conn.execute(
                "INSERT INTO task_agent_plans (plan_id, task_id, version, plan_json, "
                "approval_policy_snapshot, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?);",
                (
                    plan_id,
                    task_id,
                    version,
                    plan_json,
                    json.dumps(approval_policy_snapshot, ensure_ascii=False),
                    now,
                ),
            )
            active_conn.execute(
                "UPDATE task_agent_tasks SET current_plan_id = ?, updated_at = ? "
                "WHERE task_id = ?;",
                (plan_id, now, task_id),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
        created = get_plan(plan_id, conn=active_conn)
    if created is None:
        raise FileNotFoundError(f"Plan '{plan_id}' not found after creation.")
    return created


def get_plan(
    plan_id: str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any] | None:
    with auto_connection(conn) as (active_conn, _):
        cur = active_conn.execute(
            "SELECT * FROM task_agent_plans WHERE plan_id = ?;", (plan_id,)
        )
        row = cur.fetchone()
        return _row_to_plan(row) if row is not None else None


def list_plans(
    task_id: str, conn: Optional[sqlite3.Connection] = None
) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        cur = active_conn.execute(
            "SELECT * FROM task_agent_plans WHERE task_id = ? ORDER BY version ASC;",
            (task_id,),
        )
        return [_row_to_plan(row) for row in cur.fetchall()]


def decide_plan(
    task_id: str,
    decision: str,
    reason: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Approve or reject the task's current pending plan.

    Approval moves the task to ``ready``; rejection requires a reason and
    returns the task to ``queued`` for replanning.
    """
    if decision not in ("approve", "reject"):
        raise ValueError(f"Unknown plan decision: '{decision}'.")
    if decision == "reject" and not (reason and reason.strip()):
        raise ValueError("Rejection requires a reason.")
    with auto_connection(conn) as (active_conn, is_generated):
        task = get_task(task_id, conn=active_conn)
        if task is None:
            raise FileNotFoundError(f"Task '{task_id}' not found.")
        current_plan_id = task["current_plan_id"]
        if not current_plan_id:
            raise ValueError(f"Task '{task_id}' has no current plan.")
        plan = get_plan(str(current_plan_id), conn=active_conn)
        if plan is None:
            raise FileNotFoundError(f"Plan '{current_plan_id}' not found.")
        if plan["status"] != "pending":
            raise ValueError(
                f"Plan '{current_plan_id}' is already decided ('{plan['status']}')."
            )
        now = _now_iso()
        new_task_status = "ready" if decision == "approve" else "queued"
        _validate_task_transition(str(task["status"]), new_task_status)
        new_plan_status = "approved" if decision == "approve" else "rejected"
        event_type = "plan_approved" if decision == "approve" else "plan_rejected"
        clean_reason = reason.strip() if reason else None
        event_payload_json = redact_text(
            json.dumps(
                {"plan_id": current_plan_id, "reason": reason}, ensure_ascii=False
            )
        )

        def _do() -> None:
            active_conn.execute(
                "UPDATE task_agent_plans SET status = ?, rejection_reason = ?, decided_at = ? "
                "WHERE plan_id = ? AND status = 'pending';",
                (
                    new_plan_status,
                    redact_text(clean_reason) if clean_reason else None,
                    now,
                    current_plan_id,
                ),
            )
            active_conn.execute(
                "UPDATE task_agent_tasks SET status = ?, updated_at = ? "
                "WHERE task_id = ?;",
                (new_task_status, now, task_id),
            )
            # Same transaction as the decision: a separate append_task_event
            # call would skip committing when reusing this connection.
            cur = active_conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM task_agent_events WHERE task_id = ?;",
                (task_id,),
            )
            seq = int(cur.fetchone()["max_seq"]) + 1
            active_conn.execute(
                "INSERT INTO task_agent_events (task_id, seq, event_type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?);",
                (task_id, seq, event_type, event_payload_json, now),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
        updated = get_task(task_id, conn=active_conn)
    if updated is None:
        raise FileNotFoundError(f"Task '{task_id}' not found after decision.")
    return updated


def append_task_event(
    task_id: str,
    event_type: str,
    payload: dict[str, Any],
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Append an event to a task. Events are append-only."""
    if event_type not in TASK_EVENT_TYPES:
        raise ValueError(f"Unknown task event type: '{event_type}'")
    with auto_connection(conn) as (active_conn, is_generated):
        if get_task(task_id, conn=active_conn) is None:
            raise FileNotFoundError(f"Task '{task_id}' not found.")
        cur = active_conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM task_agent_events WHERE task_id = ?;",
            (task_id,),
        )
        seq = int(cur.fetchone()["max_seq"]) + 1
        now = _now_iso()
        payload_json = redact_text(json.dumps(payload, ensure_ascii=False))

        def _do() -> int:
            cur = active_conn.execute(
                "INSERT INTO task_agent_events (task_id, seq, event_type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?);",
                (task_id, seq, event_type, payload_json, now),
            )
            return int(cur.lastrowid or 0)

        if is_generated:
            with active_conn:
                return _do()
        else:
            return _do()


def list_task_events(
    task_id: str,
    after_id: int = 0,
    limit: int = 500,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        cur = active_conn.execute(
            "SELECT event_id, task_id, seq, event_type, payload_json, created_at "
            "FROM task_agent_events WHERE task_id = ? AND event_id > ? "
            "ORDER BY event_id ASC LIMIT ?;",
            (task_id, after_id, limit),
        )
        return [_row_to_event(row) for row in cur.fetchall()]


def claim_task(
    worker_instance_id: str,
    kind: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any] | None:
    """Atomically claim the oldest claimable task.

    ``kind`` is ``"planning"`` (``queued`` -> ``planning``) or ``"execution"``
    (``ready`` -> ``running``). Returns ``None`` when nothing is claimable or
    the race was lost.
    """
    if kind == "planning":
        from_status, to_status, order_col = "queued", "planning", "created_at"
    elif kind == "execution":
        from_status, to_status, order_col = "ready", "running", "created_at"
    else:
        raise ValueError(f"Unknown claim kind: '{kind}'.")
    with auto_connection(conn) as (active_conn, is_generated):

        def _execute() -> dict[str, Any] | None:
            cur = active_conn.execute(
                "SELECT * FROM task_agent_tasks WHERE status = ? "
                f"ORDER BY {order_col} ASC LIMIT 1;",
                (from_status,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            task_id = row["task_id"]
            now = _now_iso()
            cur2 = active_conn.execute(
                "UPDATE task_agent_tasks SET status = ?, worker_instance_id = ?, "
                "started_at = COALESCE(started_at, ?), updated_at = ? "
                "WHERE task_id = ? AND status = ?;",
                (to_status, worker_instance_id, now, now, task_id, from_status),
            )
            if cur2.rowcount == 0:
                return None
            return get_task(task_id, conn=active_conn)

        if is_generated:
            with active_conn:
                return _execute()
        else:
            return _execute()


def transition_task_status(
    task_id: str,
    to_status: str,
    result_summary: Optional[str] = None,
    error_summary: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Move a task to ``to_status`` after validating the transition."""
    with auto_connection(conn) as (active_conn, is_generated):
        task = get_task(task_id, conn=active_conn)
        if task is None:
            raise FileNotFoundError(f"Task '{task_id}' not found.")
        from_status = str(task["status"])
        if from_status == to_status:
            return task
        _validate_task_transition(from_status, to_status)
        now = _now_iso()
        finished_at = (
            now if to_status in TASK_TERMINAL_STATUSES else task["finished_at"]
        )

        def _do() -> None:
            cur = active_conn.execute(
                "UPDATE task_agent_tasks SET status = ?, "
                "result_summary = COALESCE(?, result_summary), "
                "error_summary = COALESCE(?, error_summary), "
                "updated_at = ?, finished_at = ? "
                "WHERE task_id = ? AND status = ?;",
                (
                    to_status,
                    redact_text(result_summary) if result_summary is not None else None,
                    redact_text(error_summary) if error_summary is not None else None,
                    now,
                    finished_at,
                    task_id,
                    from_status,
                ),
            )
            if cur.rowcount == 0:
                current = get_task(task_id, conn=active_conn)
                raise ValueError(
                    f"Task '{task_id}' changed concurrently "
                    f"(expected '{from_status}', now '{(current or {}).get('status')}')."
                )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
        updated = get_task(task_id, conn=active_conn)
    if updated is None:
        raise FileNotFoundError(f"Task '{task_id}' not found after transition.")
    return updated


def mark_tasks_interrupted(
    worker_instance_id: str, conn: Optional[sqlite3.Connection] = None
) -> int:
    """Mark in-flight tasks owned by ``worker_instance_id`` as interrupted."""
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> int:
            cur = active_conn.execute(
                "UPDATE task_agent_tasks SET status = 'interrupted', updated_at = ? "
                "WHERE worker_instance_id = ? AND status IN ('planning', 'running', 'cancelling');",
                (now, worker_instance_id),
            )
            return cur.rowcount

        if is_generated:
            with active_conn:
                return _do()
        else:
            return _do()


def mark_stale_tasks_interrupted(
    current_instance_id: str, conn: Optional[sqlite3.Connection] = None
) -> int:
    """Interrupt in-flight tasks not owned by ``current_instance_id``.

    Used at startup: a single worker holds the lock, so tasks claimed by a
    dead instance (or never claimed) never resume on their own.
    """
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> int:
            cur = active_conn.execute(
                "UPDATE task_agent_tasks SET status = 'interrupted', updated_at = ? "
                "WHERE status IN ('planning', 'running', 'cancelling') "
                "AND (worker_instance_id IS NULL OR worker_instance_id != ?);",
                (now, current_instance_id),
            )
            return cur.rowcount

        if is_generated:
            with active_conn:
                return _do()
        else:
            return _do()


def set_active_child(
    task_id: str,
    child_kind: str,
    child_run_id: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Record the in-flight child run a task is waiting on."""
    if child_kind not in ("agent", "coding", "research"):
        raise ValueError(f"Unknown child kind: '{child_kind}'.")
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):
        if get_task(task_id, conn=active_conn) is None:
            raise FileNotFoundError(f"Task '{task_id}' not found.")

        def _do() -> None:
            active_conn.execute(
                "UPDATE task_agent_tasks SET active_child_kind = ?, active_child_run_id = ?, "
                "updated_at = ? WHERE task_id = ?;",
                (child_kind, child_run_id, now, task_id),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
        updated = get_task(task_id, conn=active_conn)
    if updated is None:
        raise FileNotFoundError(f"Task '{task_id}' not found after update.")
    return updated


def clear_active_child(
    task_id: str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any]:
    """Clear the in-flight child run reference of a task."""
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):
        if get_task(task_id, conn=active_conn) is None:
            raise FileNotFoundError(f"Task '{task_id}' not found.")

        def _do() -> None:
            active_conn.execute(
                "UPDATE task_agent_tasks SET active_child_kind = NULL, active_child_run_id = NULL, "
                "updated_at = ? WHERE task_id = ?;",
                (now, task_id),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
        updated = get_task(task_id, conn=active_conn)
    if updated is None:
        raise FileNotFoundError(f"Task '{task_id}' not found after update.")
    return updated


def purge_terminal_tasks(
    retention_days: int = 30, conn: Optional[sqlite3.Connection] = None
) -> int:
    """Delete terminal tasks finished more than ``retention_days`` ago.

    Plans and events are removed via FK cascade. Non-terminal tasks stay.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    with auto_connection(conn) as (active_conn, is_generated):
        placeholders = ",".join("?" for _ in TASK_TERMINAL_STATUSES)

        def _do() -> int:
            cur = active_conn.execute(
                f"DELETE FROM task_agent_tasks WHERE status IN ({placeholders}) "
                f"AND finished_at IS NOT NULL AND finished_at < ?;",
                (*sorted(TASK_TERMINAL_STATUSES), cutoff),
            )
            return cur.rowcount

        if is_generated:
            with active_conn:
                return _do()
        else:
            return _do()


def list_capabilities(
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        cur = active_conn.execute(
            "SELECT * FROM task_agent_capabilities ORDER BY capability_key ASC;"
        )
        return [_row_to_capability(row) for row in cur.fetchall()]


def sync_capabilities(
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, int]:
    """Upsert the registry-derived catalog into ``task_agent_capabilities``.

    New capabilities (new builtin tools, installed plugins) are inserted with
    their default policy; the DB-owned ``enabled`` / ``approval_policy`` of
    existing rows are never overwritten. Returns ``{"inserted": n}``.
    """
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> int:
            inserted = 0
            for definition in get_capability_definitions():
                cur = active_conn.execute(
                    """
                    INSERT INTO task_agent_capabilities (
                        capability_key, adapter_kind, enabled, approval_policy, updated_at
                    ) VALUES (?, ?, 1, ?, ?)
                    ON CONFLICT(capability_key) DO NOTHING
                    """,
                    (
                        definition.key,
                        definition.adapter_kind,
                        definition.default_approval_policy,
                        now,
                    ),
                )
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    active_conn.execute(
                        "UPDATE task_agent_capabilities SET adapter_kind = ?, "
                        "updated_at = ? WHERE capability_key = ?;",
                        (definition.adapter_kind, now, definition.key),
                    )
            return inserted

        if is_generated:
            with active_conn:
                result = _do()
        else:
            result = _do()
    return {"inserted": result}


def get_capability(
    capability_key: str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any] | None:
    with auto_connection(conn) as (active_conn, _):
        cur = active_conn.execute(
            "SELECT * FROM task_agent_capabilities WHERE capability_key = ?;",
            (capability_key,),
        )
        row = cur.fetchone()
        return _row_to_capability(row) if row is not None else None


def update_capability(
    capability_key: str,
    enabled: Optional[bool] = None,
    approval_policy: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Update a capability's ``enabled`` / ``approval_policy`` (DB-owned fields)."""
    if enabled is None and approval_policy is None:
        raise ValueError("Nothing to update.")
    if approval_policy is not None and approval_policy not in ("auto", "plan_required"):
        raise ValueError(f"Unknown approval policy: '{approval_policy}'.")
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):
        if get_capability(capability_key, conn=active_conn) is None:
            raise FileNotFoundError(f"Capability '{capability_key}' not found.")

        def _do() -> None:
            if enabled is not None and approval_policy is not None:
                active_conn.execute(
                    "UPDATE task_agent_capabilities SET enabled = ?, approval_policy = ?, "
                    "updated_at = ? WHERE capability_key = ?;",
                    (1 if enabled else 0, approval_policy, now, capability_key),
                )
            elif enabled is not None:
                active_conn.execute(
                    "UPDATE task_agent_capabilities SET enabled = ?, updated_at = ? "
                    "WHERE capability_key = ?;",
                    (1 if enabled else 0, now, capability_key),
                )
            else:
                active_conn.execute(
                    "UPDATE task_agent_capabilities SET approval_policy = ?, updated_at = ? "
                    "WHERE capability_key = ?;",
                    (approval_policy, now, capability_key),
                )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
        updated = get_capability(capability_key, conn=active_conn)
    if updated is None:
        raise FileNotFoundError(
            f"Capability '{capability_key}' not found after update."
        )
    return updated
