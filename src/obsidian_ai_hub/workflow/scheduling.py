"""Scheduler -> Workflow Run dispatch service.

One place turns a Scheduler fire slot into a Workflow Run. Resolution of the
latest published Revision, ``inputs_schema`` validation, approval determination
and the Run + dispatch insert all happen on one SQLite connection inside one
transaction; the caller commits. This makes a fire slot produce at most one Run
even when the runner restarts before ``last_run`` is saved. See
``docs/workflow/specification.md`` §16.5.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.capabilities import default_approval_policy
from obsidian_ai_hub.workflow.models import validate_value_against_schema

SOURCE_RECURRING = "recurring"
SOURCE_ONE_SHOT = "one_shot"

DISPATCHED = "dispatched"
FAILED = "failed"


class WorkflowDispatchError(ValueError):
    """Expected dispatch failure that is recorded instead of raised."""


class NoPublishedRevisionError(WorkflowDispatchError):
    pass


class InputSchemaError(WorkflowDispatchError):
    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors) or "run.inputs: schema に適合しません")


def requires_approval(
    nodes: Optional[list[dict[str, Any]]],
    *,
    skip_approval: bool = False,
) -> bool:
    """True when any Agent node or ``plan_required`` capability is present.

    ``skip_approval`` is the per-workflow override: when set, the run is
    created ``queued`` and no human gate applies (spec §6.2). The approval
    boundary is otherwise fixed by Capability Policy + selected Agent ID;
    node-level overrides are not part of v1 (see the Workflow ADR). Reading the
    policy opens the task store, so callers must treat this as a pre-write
    read, not part of the run-insert transaction.
    """
    if skip_approval:
        return False
    from obsidian_ai_hub.tasks import store as task_store

    policies = {
        str(c["capability_key"]): str(c.get("approval_policy") or "plan_required")
        for c in task_store.list_capabilities()
    }
    for node in nodes or []:
        node_type = node.get("node_type")
        if node_type == "agent":
            return True
        if node_type != "capability":
            continue
        key = str((node.get("config") or {}).get("capability_key") or "")
        if not key:
            continue
        if policies.get(key, default_approval_policy(key)) == "plan_required":
            return True
    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_latest_published(
    conn: sqlite3.Connection, workflow_id: str
) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT revision_id FROM workflow_revisions "
        "WHERE workflow_id = ? AND status = 'published' "
        "ORDER BY version DESC LIMIT 1;",
        (workflow_id,),
    ).fetchone()
    if row is None:
        return None
    return workflow_store.get_revision(str(row["revision_id"]), conn=conn)


def resolve_published_revision(
    workflow_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict[str, Any]]:
    """Return the latest published revision (graph included), else None."""
    close = False
    active = conn
    if active is None:
        active = get_db_connection()
        close = True
    try:
        return _resolve_latest_published(active, workflow_id)
    finally:
        if close:
            active.close()


def create_run_for_latest_published(
    conn: sqlite3.Connection,
    workflow_id: str,
    inputs: dict[str, Any],
    *,
    reference_time: Optional[str] = None,
) -> tuple[dict[str, Any], str, str]:
    """Resolve + validate + insert a Run inside the caller's transaction.

    Returns ``(run, revision_id, initial_status)``. Raises
    ``NoPublishedRevisionError`` / ``InputSchemaError`` before any insert so
    the caller can record the failure without a dangling Run.
    ``reference_time`` is the scheduler fire slot frozen for date expressions.
    """
    revision = _resolve_latest_published(conn, workflow_id)
    if revision is None:
        raise NoPublishedRevisionError(
            f"Workflow '{workflow_id}' に公開済み Revision がありません"
        )
    errors = validate_value_against_schema(
        inputs,
        revision.get("inputs_schema") or {},
        path="run.inputs",
        allow_expressions=True,
    )
    if errors:
        raise InputSchemaError(errors)
    revision_id = str(revision["revision_id"])
    nodes = revision.get("nodes") or []
    skip_approval = workflow_store.workflow_skip_approval(workflow_id, conn=conn)
    needs_approval = requires_approval(nodes)
    initial_status = (
        "waiting_approval" if needs_approval and not skip_approval else "queued"
    )
    snapshot = {
        "inputs_schema": revision["inputs_schema"],
        "nodes": revision["nodes"],
        "edges": revision["edges"],
    }
    run_id = workflow_store.insert_run_snapshot(
        conn,
        workflow_id=workflow_id,
        revision_id=revision_id,
        inputs=inputs,
        snapshot=snapshot,
        initial_status=initial_status,
        reference_time=reference_time,
    )
    if skip_approval and needs_approval:
        workflow_store.append_event(
            run_id,
            "run_approval_skipped",
            {"reason": "workflow_skip_approval"},
            conn=conn,
        )
    run = workflow_store.get_run(run_id, conn=conn)
    assert run is not None
    return run, revision_id, initial_status


def _dispatch_row(conn: sqlite3.Connection, dispatch_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM workflow_schedule_dispatches WHERE dispatch_id = ?;",
        (dispatch_id,),
    ).fetchone()
    assert row is not None
    return dict(row)


def dispatch_recurring_slot(
    scheduler_job_id: str,
    scheduled_for: str,
    workflow_id: str,
    inputs: dict[str, Any],
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Dispatch one recurring fire slot; idempotent per slot.

    Returns ``(dispatch, run_or_None)``. When the slot already has a dispatch
    record the existing record is returned unchanged and no second Run is
    created. On expected failure the dispatch row is written with
    ``status='failed'`` and no Run.
    """
    close = False
    active = conn
    if active is None:
        active = get_db_connection()
        close = True
    try:
        def _do() -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
            existing = active.execute(
                "SELECT dispatch_id FROM workflow_schedule_dispatches "
                "WHERE source_kind = ? AND scheduler_job_id = ? "
                "AND scheduled_for = ?;",
                (SOURCE_RECURRING, scheduler_job_id, scheduled_for),
            ).fetchone()
            if existing is not None:
                return _dispatch_row(active, str(existing["dispatch_id"])), None

            dispatch_id = f"wdisp_{uuid.uuid4().hex}"
            now = _now_iso()
            run: Optional[dict[str, Any]] = None
            revision_id: Optional[str] = None
            status = DISPATCHED
            failure_reason: Optional[str] = None
            try:
                run, revision_id, _ = create_run_for_latest_published(
                    active, workflow_id, inputs, reference_time=scheduled_for
                )
            except WorkflowDispatchError as exc:
                status = FAILED
                failure_reason = str(exc)
            active.execute(
                "INSERT INTO workflow_schedule_dispatches ("
                "dispatch_id, source_kind, scheduler_job_id, scheduled_for, "
                "workflow_id, revision_id, run_id, status, failure_reason, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    dispatch_id,
                    SOURCE_RECURRING,
                    scheduler_job_id,
                    scheduled_for,
                    workflow_id,
                    revision_id,
                    run["run_id"] if run else None,
                    status,
                    failure_reason,
                    now,
                    now,
                ),
            )
            if run is not None:
                workflow_store.append_event(
                    str(run["run_id"]),
                    "run_scheduled",
                    {
                        "source_kind": SOURCE_RECURRING,
                        "scheduler_job_id": scheduler_job_id,
                        "scheduled_for": scheduled_for,
                    },
                    conn=active,
                )
            return _dispatch_row(active, dispatch_id), run

        if close:
            with active:
                return _do()
        return _do()
    finally:
        if close:
            active.close()


def get_latest_dispatch(
    scheduler_job_id: str,
    *,
    source_kind: str = SOURCE_RECURRING,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[dict[str, Any]]:
    close = False
    active = conn
    if active is None:
        active = get_db_connection()
        close = True
    try:
        row = active.execute(
            "SELECT * FROM workflow_schedule_dispatches "
            "WHERE source_kind = ? AND scheduler_job_id = ? "
            "ORDER BY scheduled_for DESC LIMIT 1;",
            (source_kind, scheduler_job_id),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        if close:
            active.close()


def list_dispatches(
    scheduler_job_ids: list[str],
    *,
    source_kind: str = SOURCE_RECURRING,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, dict[str, Any]]:
    """Return the latest dispatch per job id (for the /jobs list)."""
    if not scheduler_job_ids:
        return {}
    close = False
    active = conn
    if active is None:
        active = get_db_connection()
        close = True
    try:
        placeholders = ",".join("?" for _ in scheduler_job_ids)
        rows = active.execute(
            f"SELECT * FROM workflow_schedule_dispatches WHERE source_kind = ? "
            f"AND scheduler_job_id IN ({placeholders}) "
            "ORDER BY scheduled_for ASC;",
            (source_kind, *scheduler_job_ids),
        ).fetchall()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            record = dict(row)
            latest[str(record["scheduler_job_id"])] = record
        return latest
    finally:
        if close:
            active.close()
