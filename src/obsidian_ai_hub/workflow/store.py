"""Workflow store: definitions, revisions, graphs, runs, events (SQLite).

Table names use the ``workflow_`` prefix (``docs/workflow/specification.md``
§16.2). Events are append-only; run/node state transitions are validated here.
Writable text is redacted with the shared Task redactor before persistence.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Generator, Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.tasks.redaction import redact_text
from obsidian_ai_hub.workflow.models import (
    NODE_TERMINAL_STATUSES,
    RUN_ALLOWED_TRANSITIONS,
    RUN_TERMINAL_STATUSES,
    remap_node_references,
)

RETENTION_DAYS = 30


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


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _redacted_json(value: Any) -> str:
    return redact_text(json.dumps(value, ensure_ascii=False))


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _validate_transition(from_status: str, to_status: str) -> None:
    allowed = RUN_ALLOWED_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise ValueError(
            f"Illegal workflow run transition: '{from_status}' -> '{to_status}'."
        )


# --- Workflows -------------------------------------------------------------


def create_workflow(
    name: str,
    description: str = "",
    *,
    inputs_schema: Optional[dict[str, Any]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Create a workflow and its initial draft revision."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("workflow name must not be blank")
    workflow_id = _new_id("wf")
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):
        def _do() -> None:
            active_conn.execute(
                "INSERT INTO workflows (workflow_id, name, description, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
                (workflow_id, name.strip(), description or "", now, now),
            )
            create_revision(
                workflow_id,
                inputs_schema or {"type": "object"},
                conn=active_conn,
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
    workflow = get_workflow(workflow_id, conn=conn)
    assert workflow is not None
    workflow["revision"] = get_latest_revision(workflow_id, conn=conn)
    return workflow


def get_workflow(
    workflow_id: str, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        row = active_conn.execute(
            "SELECT * FROM workflows WHERE workflow_id = ?;", (workflow_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def list_workflows(
    *, limit: int = 20, offset: int = 0, conn: Optional[sqlite3.Connection] = None
) -> tuple[list[dict[str, Any]], int]:
    with auto_connection(conn) as (active_conn, _):
        rows = active_conn.execute(
            "SELECT * FROM workflows ORDER BY created_at DESC LIMIT ? OFFSET ?;",
            (limit, offset),
        ).fetchall()
        total = active_conn.execute("SELECT COUNT(*) AS n FROM workflows;").fetchone()[
            "n"
        ]
    return [dict(row) for row in rows], int(total)


def update_workflow(
    workflow_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Update a workflow's name and/or description.

    Only the provided fields change. A blank name is rejected so the
    workflow keeps a usable display label. Raises ``FileNotFoundError`` when
    the workflow does not exist and ``ValueError`` for a blank name.
    """
    if name is None and description is None:
        existing = get_workflow(workflow_id, conn=conn)
        if existing is None:
            raise FileNotFoundError(f"Workflow '{workflow_id}' not found.")
        return existing
    if name is not None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("workflow name must not be blank")
        name = name.strip()
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            row = active_conn.execute(
                "SELECT workflow_id FROM workflows WHERE workflow_id = ?;",
                (workflow_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"Workflow '{workflow_id}' not found.")
            assignments = ["updated_at = ?"]
            params: list[Any] = [now]
            if name is not None:
                assignments.append("name = ?")
                params.append(name)
            if description is not None:
                assignments.append("description = ?")
                params.append(description)
            params.append(workflow_id)
            active_conn.execute(
                f"UPDATE workflows SET {', '.join(assignments)} "
                "WHERE workflow_id = ?;",
                params,
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
    updated = get_workflow(workflow_id, conn=conn)
    assert updated is not None
    return updated


def delete_workflow(
    workflow_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> dict[str, int]:
    """Delete a workflow and its entire aggregate (definition and run history).

    Non-terminal runs block deletion so no in-flight run is orphaned. Runs,
    nodes, activations, events and schedule dispatches are removed together
    with revisions and their graphs in one transaction. Raises
    ``FileNotFoundError`` when the workflow does not exist and ``ValueError``
    when a non-terminal run is present.
    """
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> dict[str, int]:
            row = active_conn.execute(
                "SELECT workflow_id FROM workflows WHERE workflow_id = ?;",
                (workflow_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"Workflow '{workflow_id}' not found.")
            placeholders = ", ".join("?" for _ in RUN_TERMINAL_STATUSES)
            blocking = active_conn.execute(
                "SELECT COUNT(*) AS n FROM workflow_runs WHERE workflow_id = ? "
                f"AND status NOT IN ({placeholders});",
                (workflow_id, *sorted(RUN_TERMINAL_STATUSES)),
            ).fetchone()["n"]
            if int(blocking) > 0:
                raise ValueError(
                    f"Workflow '{workflow_id}' has {int(blocking)} non-terminal "
                    "run(s) and cannot be deleted."
                )
            revision_count = active_conn.execute(
                "SELECT COUNT(*) AS n FROM workflow_revisions "
                "WHERE workflow_id = ?;",
                (workflow_id,),
            ).fetchone()["n"]
            run_count = active_conn.execute(
                "SELECT COUNT(*) AS n FROM workflow_runs WHERE workflow_id = ?;",
                (workflow_id,),
            ).fetchone()["n"]
            active_conn.execute(
                "DELETE FROM workflow_events WHERE run_id IN "
                "(SELECT run_id FROM workflow_runs WHERE workflow_id = ?);",
                (workflow_id,),
            )
            active_conn.execute(
                "DELETE FROM workflow_run_nodes WHERE run_id IN "
                "(SELECT run_id FROM workflow_runs WHERE workflow_id = ?);",
                (workflow_id,),
            )
            active_conn.execute(
                "DELETE FROM workflow_activations WHERE run_id IN "
                "(SELECT run_id FROM workflow_runs WHERE workflow_id = ?);",
                (workflow_id,),
            )
            active_conn.execute(
                "DELETE FROM workflow_runs WHERE workflow_id = ?;", (workflow_id,)
            )
            active_conn.execute(
                "DELETE FROM workflow_edges WHERE revision_id IN "
                "(SELECT revision_id FROM workflow_revisions WHERE workflow_id = ?);",
                (workflow_id,),
            )
            active_conn.execute(
                "DELETE FROM workflow_nodes WHERE revision_id IN "
                "(SELECT revision_id FROM workflow_revisions WHERE workflow_id = ?);",
                (workflow_id,),
            )
            active_conn.execute(
                "DELETE FROM workflow_revisions WHERE workflow_id = ?;",
                (workflow_id,),
            )
            active_conn.execute(
                "DELETE FROM workflow_schedule_dispatches WHERE workflow_id = ?;",
                (workflow_id,),
            )
            active_conn.execute(
                "DELETE FROM workflows WHERE workflow_id = ?;", (workflow_id,)
            )
            return {
                "revisions": int(revision_count),
                "runs": int(run_count),
            }

        if is_generated:
            with active_conn:
                return _do()
        return _do()


# --- Revisions -------------------------------------------------------------


def create_revision(
    workflow_id: str,
    inputs_schema: Optional[dict[str, Any]] = None,
    *,
    source_revision_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Create the next draft revision for a workflow.

    When the workflow has a published revision (or an explicit
    ``source_revision_id`` is given), its graph and ``inputs_schema`` are
    copied into the new draft with fresh node/edge ids so the source stays
    immutable. With no published revision the draft starts blank, preserving
    initial workflow creation.
    """
    revision_id = _new_id("wrev")
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            source = _resolve_source_revision(
                active_conn, workflow_id, source_revision_id
            )
            row = active_conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM workflow_revisions "
                "WHERE workflow_id = ?;",
                (workflow_id,),
            ).fetchone()
            version = int(row["v"]) + 1
            if inputs_schema is not None:
                schema = inputs_schema
            elif source is not None:
                schema = source.get("inputs_schema") or {"type": "object"}
            else:
                schema = {"type": "object"}
            active_conn.execute(
                "INSERT INTO workflow_revisions (revision_id, workflow_id, version, "
                "status, inputs_schema, created_at, updated_at) "
                "VALUES (?, ?, ?, 'draft', ?, ?, ?);",
                (
                    revision_id,
                    workflow_id,
                    version,
                    _redacted_json(schema),
                    now,
                    now,
                ),
            )
            if source is not None:
                nodes, edges = _clone_graph(
                    source.get("nodes") or [], source.get("edges") or []
                )
                _insert_graph(active_conn, revision_id, nodes, edges)

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
    revision = get_revision(revision_id, conn=conn)
    assert revision is not None
    return revision


def _resolve_source_revision(
    conn: sqlite3.Connection,
    workflow_id: str,
    source_revision_id: Optional[str],
) -> Optional[dict[str, Any]]:
    """Return the revision to copy from, or None for a blank draft.

    An explicit ``source_revision_id`` is honoured as-is (any status). Without
    one, the workflow's current published revision is used when present.
    """
    if source_revision_id is not None:
        source = get_revision(source_revision_id, conn=conn)
        if source is None:
            raise FileNotFoundError(
                f"Source revision '{source_revision_id}' not found."
            )
        if str(source.get("workflow_id")) != workflow_id:
            raise ValueError(
                f"Source revision '{source_revision_id}' belongs to another workflow."
            )
        return source
    row = conn.execute(
        "SELECT revision_id FROM workflow_revisions "
        "WHERE workflow_id = ? AND status = 'published' "
        "ORDER BY version DESC LIMIT 1;",
        (workflow_id,),
    ).fetchone()
    if row is None:
        return None
    return get_revision(str(row["revision_id"]), conn=conn)


def _clone_graph(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deep-copy a graph with fresh node/edge ids and rewritten references."""
    id_map = {str(node["node_id"]): _new_uuid() for node in nodes}
    cloned_nodes: list[dict[str, Any]] = []
    for node in nodes:
        parent = node.get("parent_loop_node_id")
        config = remap_node_references(node.get("config") or {}, id_map)
        if isinstance(config, dict) and config.get("entry_node_id") in id_map:
            config["entry_node_id"] = id_map[config["entry_node_id"]]
        cloned_nodes.append(
            {
                "node_id": id_map[str(node["node_id"])],
                "node_type": node["node_type"],
                "label": node.get("label"),
                "config": config,
                "parent_loop_node_id": id_map.get(str(parent)) if parent else None,
                "ui_position": node.get("ui_position"),
            }
        )
    cloned_edges = [
        {
            "edge_id": _new_uuid(),
            "source_node_id": id_map[str(edge["source_node_id"])],
            "target_node_id": id_map[str(edge["target_node_id"])],
            "edge_kind": edge.get("edge_kind") or "normal",
            "condition": remap_node_references(edge.get("condition"), id_map),
            "order_index": int(edge.get("order_index") or 0),
        }
        for edge in edges
    ]
    return cloned_nodes, cloned_edges


def _insert_graph(
    conn: sqlite3.Connection,
    revision_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    """Insert nodes and edges for a revision (no deletes; caller manages that)."""
    for node in nodes:
        conn.execute(
            "INSERT INTO workflow_nodes (node_id, revision_id, node_type, "
            "label, config_json, parent_loop_node_id, ui_position_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?);",
            (
                str(node["node_id"]),
                revision_id,
                str(node["node_type"]),
                node.get("label"),
                _redacted_json(node.get("config") or {}),
                node.get("parent_loop_node_id"),
                json.dumps(node.get("ui_position"), ensure_ascii=False)
                if node.get("ui_position") is not None
                else None,
            ),
        )
    for edge in edges:
        conn.execute(
            "INSERT INTO workflow_edges (edge_id, revision_id, "
            "source_node_id, target_node_id, edge_kind, condition_json, "
            "order_index) VALUES (?, ?, ?, ?, ?, ?, ?);",
            (
                str(edge["edge_id"]),
                revision_id,
                str(edge["source_node_id"]),
                str(edge["target_node_id"]),
                str(edge.get("edge_kind") or "normal"),
                _redacted_json(edge["condition"])
                if edge.get("condition") is not None
                else None,
                int(edge.get("order_index") or 0),
            ),
        )


def get_revision(
    revision_id: str, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        row = active_conn.execute(
            "SELECT * FROM workflow_revisions WHERE revision_id = ?;",
            (revision_id,),
        ).fetchone()
        if row is None:
            return None
        nodes = [
            dict(n)
            for n in active_conn.execute(
                "SELECT * FROM workflow_nodes WHERE revision_id = ? "
                "ORDER BY rowid ASC;",
                (revision_id,),
            ).fetchall()
        ]
        edges = [
            dict(e)
            for e in active_conn.execute(
                "SELECT * FROM workflow_edges WHERE revision_id = ? "
                "ORDER BY order_index ASC, rowid ASC;",
                (revision_id,),
            ).fetchall()
        ]
    return _revision_row(row, nodes, edges)


def _revision_row(
    row: sqlite3.Row, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, Any]:
    revision = dict(row)
    revision["inputs_schema"] = _loads(revision.get("inputs_schema"), {})
    for node in nodes:
        node["config"] = _loads(node.get("config_json"), {})
        node["ui_position"] = _loads(node.get("ui_position_json"), None)
    for edge in edges:
        edge["condition"] = _loads(edge.get("condition_json"), None)
    revision["nodes"] = nodes
    revision["edges"] = edges
    return revision


def list_schedulable_workflows(
    *, conn: Optional[sqlite3.Connection] = None
) -> list[dict[str, Any]]:
    """List workflows that have a published revision, with its input schema.

    Backs the Scheduler Job target picker; only runnable workflows are shown.
    """
    with auto_connection(conn) as (active_conn, _):
        rows = active_conn.execute(
            "SELECT w.workflow_id, w.name, w.description, "
            "r.revision_id, r.version, r.inputs_schema "
            "FROM workflows w JOIN workflow_revisions r "
            "ON r.workflow_id = w.workflow_id AND r.status = 'published' "
            "ORDER BY w.name ASC;",
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        record["inputs_schema"] = _loads(record.get("inputs_schema"), {"type": "object"})
        items.append(record)
    return items


def get_latest_revision(
    workflow_id: str, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        row = active_conn.execute(
            "SELECT revision_id FROM workflow_revisions WHERE workflow_id = ? "
            "ORDER BY version DESC LIMIT 1;",
            (workflow_id,),
        ).fetchone()
    return get_revision(str(row["revision_id"]), conn=conn) if row else None


def list_revisions(
    workflow_id: str, conn: Optional[sqlite3.Connection] = None
) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        rows = active_conn.execute(
            "SELECT revision_id FROM workflow_revisions WHERE workflow_id = ? "
            "ORDER BY version DESC;",
            (workflow_id,),
        ).fetchall()
    return [r for r in (get_revision(str(row["revision_id"]), conn=conn) for row in rows) if r]


def update_revision_schema(
    revision_id: str,
    inputs_schema: dict[str, Any],
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            revision = _require_draft(active_conn, revision_id)
            active_conn.execute(
                "UPDATE workflow_revisions SET inputs_schema = ?, updated_at = ? "
                "WHERE revision_id = ?;",
                (
                    _redacted_json(inputs_schema),
                    now,
                    revision["revision_id"],
                ),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()


def set_revision_graph(
    revision_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Replace a draft revision's nodes and edges."""
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            _require_draft(active_conn, revision_id)
            active_conn.execute(
                "DELETE FROM workflow_edges WHERE revision_id = ?;", (revision_id,)
            )
            active_conn.execute(
                "DELETE FROM workflow_nodes WHERE revision_id = ?;", (revision_id,)
            )
            _insert_graph(active_conn, revision_id, nodes, edges)
            active_conn.execute(
                "UPDATE workflow_revisions SET updated_at = ? WHERE revision_id = ?;",
                (now, revision_id),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()


def publish_revision(
    revision_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any]:
    """Publish a draft, superseding any previously published revision."""
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            revision = _require_draft(active_conn, revision_id)
            active_conn.execute(
                "UPDATE workflow_revisions SET status = 'superseded', updated_at = ? "
                "WHERE workflow_id = ? AND status = 'published';",
                (now, revision["workflow_id"]),
            )
            active_conn.execute(
                "UPDATE workflow_revisions SET status = 'published', updated_at = ? "
                "WHERE revision_id = ?;",
                (now, revision_id),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
    published = get_revision(revision_id, conn=conn)
    assert published is not None
    return published


def delete_revision(
    revision_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> None:
    """Delete a draft or superseded revision together with its graph.

    Only ``draft`` and ``superseded`` revisions can be deleted; a
    ``published`` revision is rejected so a workflow never silently loses
    its runnable revision. The status check is a single conditional
    ``DELETE`` so a concurrent publish wins the race instead of losing
    its graph. Runs that reference the deleted revision are kept: they
    carry their own immutable graph snapshot.
    """
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            cur = active_conn.execute(
                "DELETE FROM workflow_revisions WHERE revision_id = ? "
                "AND status IN ('draft', 'superseded');",
                (revision_id,),
            )
            if cur.rowcount == 1:
                active_conn.execute(
                    "DELETE FROM workflow_edges WHERE revision_id = ?;",
                    (revision_id,),
                )
                active_conn.execute(
                    "DELETE FROM workflow_nodes WHERE revision_id = ?;",
                    (revision_id,),
                )
                return
            row = active_conn.execute(
                "SELECT status FROM workflow_revisions WHERE revision_id = ?;",
                (revision_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(
                    f"Revision '{revision_id}' not found."
                )
            raise ValueError(
                f"Revision '{revision_id}' is published and cannot be deleted."
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()


def _require_draft(conn: sqlite3.Connection, revision_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM workflow_revisions WHERE revision_id = ?;", (revision_id,)
    ).fetchone()
    if row is None:
        raise FileNotFoundError(f"Revision '{revision_id}' not found.")
    if str(row["status"]) != "draft":
        raise ValueError(f"Revision '{revision_id}' is not editable (draft only).")
    return row


# --- Runs ------------------------------------------------------------------


def _insert_run(
    conn: sqlite3.Connection,
    *,
    workflow_id: str,
    revision_id: str,
    inputs: dict[str, Any],
    snapshot: dict[str, Any],
    initial_status: str,
    source_run_id: Optional[str] = None,
) -> str:
    """Insert one run row (redacted) and return its id."""
    if initial_status not in ("queued", "waiting_approval"):
        raise ValueError(f"Unsupported initial run status: {initial_status}")
    run_id = _new_id("wrun")
    now = _now_iso()
    conn.execute(
        "INSERT INTO workflow_runs (run_id, workflow_id, revision_id, status, "
        "inputs_json, graph_snapshot_json, source_run_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (
            run_id,
            workflow_id,
            revision_id,
            initial_status,
            _redacted_json(inputs),
            _redacted_json(snapshot),
            source_run_id,
            now,
            now,
        ),
    )
    return run_id


def create_run(
    workflow_id: str,
    revision_id: str,
    inputs: dict[str, Any],
    *,
    initial_status: str = "queued",
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Create a run with an immutable graph + inputs snapshot.

    ``initial_status`` lets callers insert an approval-required run
    directly as ``waiting_approval`` so a worker can never claim it
    before the human gate (spec §7.2).
    """
    run_id: str | None = None
    with auto_connection(conn) as (active_conn, is_generated):
        revision = active_conn.execute(
            "SELECT * FROM workflow_revisions WHERE revision_id = ?;",
            (revision_id,),
        ).fetchone()
        if revision is None or str(revision["workflow_id"]) != workflow_id:
            raise ValueError(f"Revision '{revision_id}' does not belong to the workflow.")
        if str(revision["status"]) != "published":
            raise ValueError("Only a published revision can start a run.")
        full = get_revision(revision_id, conn=active_conn)
        assert full is not None
        snapshot = {
            "inputs_schema": full["inputs_schema"],
            "nodes": full["nodes"],
            "edges": full["edges"],
        }

        def _do() -> None:
            nonlocal run_id
            run_id = _insert_run(
                active_conn,
                workflow_id=workflow_id,
                revision_id=revision_id,
                inputs=inputs,
                snapshot=snapshot,
                initial_status=initial_status,
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
    created = get_run(str(run_id), conn=conn)
    assert created is not None
    return created


def insert_run_snapshot(
    conn: sqlite3.Connection,
    *,
    workflow_id: str,
    revision_id: str,
    inputs: dict[str, Any],
    snapshot: dict[str, Any],
    initial_status: str,
) -> str:
    """Insert a run from a caller-built snapshot on an existing transaction.

    Callers (scheduler dispatch, manual run creation) own the transaction so
    the run row and any related row (e.g. a dispatch record) commit together.
    """
    return _insert_run(
        conn,
        workflow_id=workflow_id,
        revision_id=revision_id,
        inputs=inputs,
        snapshot=snapshot,
        initial_status=initial_status,
    )


def create_rerun_run(
    source_run: dict[str, Any],
    inputs: dict[str, Any],
    *,
    initial_status: str = "queued",
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Create a new run from a past run's graph snapshot and inputs.

    The source run's ``graph_snapshot`` is copied, so a rerun works even after
    the source revision is superseded. ``source_run_id`` is recorded for audit.
    """
    run_id: str | None = None
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            nonlocal run_id
            run_id = _insert_run(
                active_conn,
                workflow_id=str(source_run["workflow_id"]),
                revision_id=str(source_run["revision_id"]),
                inputs=inputs,
                snapshot=source_run.get("graph_snapshot") or {},
                initial_status=initial_status,
                source_run_id=str(source_run["run_id"]),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
    created = get_run(str(run_id), conn=conn)
    assert created is not None
    return created


def get_run(
    run_id: str, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        row = active_conn.execute(
            "SELECT * FROM workflow_runs WHERE run_id = ?;", (run_id,)
        ).fetchone()
    if row is None:
        return None
    run = dict(row)
    run["inputs"] = _loads(run.get("inputs_json"), {})
    run["graph_snapshot"] = _loads(run.get("graph_snapshot_json"), {})
    return run


def list_runs(
    *,
    workflow_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[list[dict[str, Any]], int]:
    with auto_connection(conn) as (active_conn, _):
        if workflow_id:
            rows = active_conn.execute(
                "SELECT run_id FROM workflow_runs WHERE workflow_id = ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?;",
                (workflow_id, limit, offset),
            ).fetchall()
            total = active_conn.execute(
                "SELECT COUNT(*) AS n FROM workflow_runs WHERE workflow_id = ?;",
                (workflow_id,),
            ).fetchone()["n"]
        else:
            rows = active_conn.execute(
                "SELECT run_id FROM workflow_runs ORDER BY created_at DESC "
                "LIMIT ? OFFSET ?;",
                (limit, offset),
            ).fetchall()
            total = active_conn.execute(
                "SELECT COUNT(*) AS n FROM workflow_runs;"
            ).fetchone()["n"]
    runs = [r for r in (get_run(str(row["run_id"]), conn=conn) for row in rows) if r]
    return runs, int(total)


def claim_run(
    worker_instance_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict[str, Any]]:
    """Atomically claim the oldest queued run (``queued`` -> ``running``)."""
    with auto_connection(conn) as (active_conn, is_generated):

        def _execute() -> Optional[dict[str, Any]]:
            row = active_conn.execute(
                "SELECT run_id FROM workflow_runs WHERE status = 'queued' "
                "ORDER BY created_at ASC LIMIT 1;",
            ).fetchone()
            if row is None:
                return None
            run_id = str(row["run_id"])
            now = _now_iso()
            cur = active_conn.execute(
                "UPDATE workflow_runs SET status = 'running', worker_instance_id = ?, "
                "started_at = COALESCE(started_at, ?), updated_at = ? "
                "WHERE run_id = ? AND status = 'queued';",
                (worker_instance_id, now, now, run_id),
            )
            if cur.rowcount == 0:
                return None
            return get_run(run_id, conn=active_conn)

        if is_generated:
            with active_conn:
                return _execute()
        return _execute()


def transition_run_status(
    run_id: str,
    to_status: str,
    *,
    result_summary: Optional[str] = None,
    error_summary: Optional[str] = None,
    worker_instance_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> dict[str, Any]:
            run = get_run(run_id, conn=active_conn)
            if run is None:
                raise FileNotFoundError(f"Workflow run '{run_id}' not found.")
            from_status = str(run["status"])
            if from_status == to_status:
                return run
            _validate_transition(from_status, to_status)
            now = _now_iso()
            finished_at = now if to_status in RUN_TERMINAL_STATUSES else run["finished_at"]
            active_conn.execute(
                "UPDATE workflow_runs SET status = ?, "
                "result_summary = COALESCE(?, result_summary), "
                "error_summary = COALESCE(?, error_summary), "
                "worker_instance_id = COALESCE(?, worker_instance_id), "
                "updated_at = ?, finished_at = ? WHERE run_id = ?;",
                (
                    to_status,
                    redact_text(result_summary) if result_summary is not None else None,
                    redact_text(error_summary) if error_summary is not None else None,
                    worker_instance_id,
                    now,
                    finished_at,
                    run_id,
                ),
            )
            return get_run(run_id, conn=active_conn)  # type: ignore[return-value]

        if is_generated:
            with active_conn:
                return _do()
        return _do()


IMMEDIATE_CANCEL_STATUSES = frozenset(
    {"queued", "waiting_approval", "waiting_hitl", "waiting_attention"}
)
COOPERATIVE_CANCEL_STATUSES = frozenset({"running", "cancelling"})


def request_run_cancel(
    run_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any]:
    """Atomically record a cancel request and return the updated run.

    Waiting/queued runs stop immediately (``cancelled``); a ``running`` run
    moves to ``cancelling`` so the engine and the in-flight bridge Task can
    stop cooperatively. The ``run_cancel_requested`` event is written in the
    same transaction so the audit trail never lags the status. Raises
    ``ValueError`` for terminal runs.
    """
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> dict[str, Any]:
            run = get_run(run_id, conn=active_conn)
            if run is None:
                raise FileNotFoundError(f"Workflow run '{run_id}' not found.")
            from_status = str(run["status"])
            if from_status in IMMEDIATE_CANCEL_STATUSES:
                to_status = "cancelled"
            elif from_status in COOPERATIVE_CANCEL_STATUSES:
                to_status = "cancelling"
            else:
                raise ValueError(f"cannot cancel from '{from_status}'")
            if from_status != to_status:
                _validate_transition(from_status, to_status)
            now = _now_iso()
            finished_at = (
                now if to_status in RUN_TERMINAL_STATUSES else run["finished_at"]
            )
            cur = active_conn.execute(
                "UPDATE workflow_runs SET status = ?, updated_at = ?, "
                "finished_at = ? WHERE run_id = ? AND status = ?;",
                (to_status, now, finished_at, run_id, from_status),
            )
            if cur.rowcount == 0:
                # A concurrent transition won; never clobber it.
                current = get_run(run_id, conn=active_conn)
                if current is None:
                    raise FileNotFoundError(f"Workflow run '{run_id}' not found.")
                now_status = str(current["status"])
                if now_status in ("cancelling", "cancelled"):
                    return current
                raise ValueError(f"cannot cancel from '{now_status}'")
            append_event(
                run_id,
                "run_cancel_requested",
                {"from": from_status, "to": to_status},
                conn=active_conn,
            )
            return get_run(run_id, conn=active_conn)  # type: ignore[return-value]

        if is_generated:
            with active_conn:
                return _do()
        return _do()


def list_cancel_targets(
    run_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> dict[str, list[str]]:
    """Return in-flight references a cancel request must propagate to.

    ``bridge_task_ids`` are the short-lived Task rows ownership of which the
    Capability runner delegated to the adapter; ``hitl_run_ids`` are HITL
    waits whose answer must not requeue a cancelled run.
    """
    bridge_task_ids: list[str] = []
    hitl_run_ids: list[str] = []
    for node in list_run_nodes(run_id, conn=conn):
        if str(node.get("status")) in ("running", "waiting_hitl"):
            bridge = node.get("bridge_task_id")
            if bridge:
                bridge_task_ids.append(str(bridge))
            hitl = node.get("hitl_run_id")
            if hitl:
                hitl_run_ids.append(str(hitl))
    return {"bridge_task_ids": bridge_task_ids, "hitl_run_ids": hitl_run_ids}


def mark_stale_runs_interrupted(
    instance_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> int:
    """Startup recovery: interrupt runs owned by other instances."""
    return _interrupt_runs(
        "worker_instance_id IS NOT NULL AND worker_instance_id != ? "
        "AND status IN ('running','cancelling')",
        (instance_id,),
        conn=conn,
    )


def mark_own_runs_interrupted(
    instance_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> int:
    """Shutdown recovery: interrupt runs owned by this instance."""
    return _interrupt_runs(
        "worker_instance_id = ? AND status IN ('running','cancelling')",
        (instance_id,),
        conn=conn,
    )


def _interrupt_runs(
    where: str,
    params: tuple[Any, ...],
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    now = _now_iso()
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> int:
            cur = active_conn.execute(
                f"UPDATE workflow_runs SET status = 'interrupted', updated_at = ? "
                f"WHERE {where};",
                (now, *params),
            )
            return int(cur.rowcount)

        if is_generated:
            with active_conn:
                return _do()
        return _do()


def purge_terminal_runs(
    *, days: int = RETENTION_DAYS, conn: Optional[sqlite3.Connection] = None
) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> int:
            runs = [
                str(row["run_id"])
                for row in active_conn.execute(
                    "SELECT run_id FROM workflow_runs WHERE status IN "
                    "('completed','incomplete','failed','cancelled') "
                    "AND finished_at IS NOT NULL AND finished_at < ?;",
                    (cutoff,),
                ).fetchall()
            ]
            for run_id in runs:
                active_conn.execute(
                    "DELETE FROM workflow_events WHERE run_id = ?;", (run_id,)
                )
                active_conn.execute(
                    "DELETE FROM workflow_run_nodes WHERE run_id = ?;", (run_id,)
                )
                active_conn.execute(
                    "DELETE FROM workflow_activations WHERE run_id = ?;", (run_id,)
                )
                active_conn.execute(
                    "DELETE FROM workflow_runs WHERE run_id = ?;", (run_id,)
                )
            return len(runs)

        if is_generated:
            with active_conn:
                return _do()
        return _do()


# --- Run nodes & activations ----------------------------------------------


def get_or_create_activation(
    run_id: str,
    node_id: str,
    iteration_context: Optional[dict[str, Any]],
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> str:
    """Return the stable activation id for a logical node invocation."""
    context_json = (
        json.dumps(iteration_context, ensure_ascii=False, sort_keys=True)
        if iteration_context is not None
        else None
    )
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> str:
            if context_json is None:
                row = active_conn.execute(
                    "SELECT activation_id FROM workflow_activations WHERE run_id = ? "
                    "AND node_id = ? AND iteration_context IS NULL LIMIT 1;",
                    (run_id, node_id),
                ).fetchone()
            else:
                row = active_conn.execute(
                    "SELECT activation_id FROM workflow_activations WHERE run_id = ? "
                    "AND node_id = ? AND iteration_context = ? LIMIT 1;",
                    (run_id, node_id, context_json),
                ).fetchone()
            if row is not None:
                return str(row["activation_id"])
            activation_id = _new_uuid()
            active_conn.execute(
                "INSERT INTO workflow_activations (activation_id, run_id, node_id, "
                "iteration_context, created_at) VALUES (?, ?, ?, ?, ?);",
                (activation_id, run_id, node_id, context_json, _now_iso()),
            )
            return activation_id

        if is_generated:
            with active_conn:
                return _do()
        return _do()


def get_run_node(
    activation_id: str,
    attempt: int = 1,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        row = active_conn.execute(
            "SELECT * FROM workflow_run_nodes WHERE activation_id = ? AND attempt = ?;",
            (activation_id, attempt),
        ).fetchone()
    if row is None:
        return None
    return _run_node_row(row)


def get_latest_run_node(
    activation_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict[str, Any]]:
    """Return the highest-attempt run_node row for an activation."""
    with auto_connection(conn) as (active_conn, _):
        row = active_conn.execute(
            "SELECT * FROM workflow_run_nodes WHERE activation_id = ? "
            "ORDER BY attempt DESC LIMIT 1;",
            (activation_id,),
        ).fetchone()
    if row is None:
        return None
    return _run_node_row(row)


def _run_node_row(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    record["inputs"] = _loads(record.get("inputs_json"), {})
    record["output"] = _loads(record.get("output_json"), {})
    record["effects"] = _loads(record.get("effects_json"), [])
    return record


def upsert_run_node(
    *,
    run_id: str,
    node_id: str,
    activation_id: str,
    attempt: int,
    status: str,
    inputs: Optional[dict[str, Any]] = None,
    output: Optional[dict[str, Any]] = None,
    output_summary: Optional[str] = None,
    error_summary: Optional[str] = None,
    bridge_task_id: Optional[str] = None,
    child_kind: Optional[str] = None,
    child_run_id: Optional[str] = None,
    hitl_run_id: Optional[str] = None,
    effects: Optional[tuple[str, ...]] = None,
    cancel_outcome: Optional[str] = None,
    attention_reason: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    now = _now_iso()
    finished = now if status in NODE_TERMINAL_STATUSES or status == "needs_attention" else None
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            active_conn.execute(
                "INSERT INTO workflow_run_nodes (run_id, node_id, activation_id, "
                "attempt, status, inputs_json, output_json, output_summary, "
                "error_summary, bridge_task_id, child_kind, child_run_id, "
                "hitl_run_id, effects_json, cancel_outcome, attention_reason, "
                "started_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(activation_id, attempt) DO UPDATE SET "
                "status = excluded.status, "
                "inputs_json = COALESCE(excluded.inputs_json, inputs_json), "
                "output_json = COALESCE(excluded.output_json, output_json), "
                "output_summary = COALESCE(excluded.output_summary, output_summary), "
                "error_summary = COALESCE(excluded.error_summary, error_summary), "
                "bridge_task_id = COALESCE(excluded.bridge_task_id, bridge_task_id), "
                "child_kind = COALESCE(excluded.child_kind, child_kind), "
                "child_run_id = COALESCE(excluded.child_run_id, child_run_id), "
                "hitl_run_id = COALESCE(excluded.hitl_run_id, hitl_run_id), "
                "effects_json = COALESCE(excluded.effects_json, effects_json), "
                "cancel_outcome = COALESCE(excluded.cancel_outcome, cancel_outcome), "
                "attention_reason = COALESCE(excluded.attention_reason, attention_reason), "
                "finished_at = excluded.finished_at;",
                (
                    run_id,
                    node_id,
                    activation_id,
                    attempt,
                    status,
                    _redacted_json(inputs) if inputs is not None else None,
                    _redacted_json(output) if output is not None else None,
                    redact_text(output_summary) if output_summary is not None else None,
                    redact_text(error_summary) if error_summary is not None else None,
                    bridge_task_id,
                    child_kind,
                    child_run_id,
                    hitl_run_id,
                    _redacted_json(list(effects)) if effects is not None else None,
                    cancel_outcome,
                    redact_text(attention_reason)
                    if attention_reason is not None
                    else None,
                    now,
                    finished,
                ),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()


def set_run_node_bridge(
    *,
    run_id: str,
    node_id: str,
    activation_id: str,
    attempt: int,
    bridge_task_id: str,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Record the in-flight bridge Task id on a running node.

    Persisted right after the bridge Task is created and before the external
    call, so a concurrent cancel can find and stop it. A no-op when the row
    does not exist yet (the caller inserts it as ``running`` first).
    """
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            active_conn.execute(
                "UPDATE workflow_run_nodes SET bridge_task_id = ? "
                "WHERE run_id = ? AND node_id = ? "
                "AND activation_id = ? AND attempt = ?;",
                (bridge_task_id, run_id, node_id, activation_id, attempt),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()


def list_run_nodes(
    run_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        rows = active_conn.execute(
            "SELECT * FROM workflow_run_nodes WHERE run_id = ? "
            "ORDER BY started_at ASC, node_id ASC;",
            (run_id,),
        ).fetchall()
    return [_run_node_row(row) for row in rows]


def list_activations(
    run_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        rows = active_conn.execute(
            "SELECT * FROM workflow_activations WHERE run_id = ? ORDER BY created_at ASC;",
            (run_id,),
        ).fetchall()
    records = [dict(row) for row in rows]
    for record in records:
        record["iteration_context"] = _loads(record.get("iteration_context"), None)
    return records


def find_activation(
    run_id: str,
    node_id: str,
    iteration_context: Optional[dict[str, Any]],
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[dict[str, Any]]:
    context_json = (
        json.dumps(iteration_context, ensure_ascii=False, sort_keys=True)
        if iteration_context is not None
        else None
    )
    with auto_connection(conn) as (active_conn, _):
        if context_json is None:
            row = active_conn.execute(
                "SELECT * FROM workflow_activations WHERE run_id = ? AND node_id = ? "
                "AND iteration_context IS NULL LIMIT 1;",
                (run_id, node_id),
            ).fetchone()
        else:
            row = active_conn.execute(
                "SELECT * FROM workflow_activations WHERE run_id = ? AND node_id = ? "
                "AND iteration_context = ? LIMIT 1;",
                (run_id, node_id, context_json),
            ).fetchone()
    return dict(row) if row is not None else None


# --- Events ----------------------------------------------------------------


def append_event(
    run_id: str,
    event_type: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    with auto_connection(conn) as (active_conn, is_generated):

        def _do() -> dict[str, Any]:
            row = active_conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS s FROM workflow_events "
                "WHERE run_id = ?;",
                (run_id,),
            ).fetchone()
            seq = int(row["s"]) + 1
            event_id = _new_id("wevt")
            created = _now_iso()
            active_conn.execute(
                "INSERT INTO workflow_events (event_id, run_id, seq, event_type, "
                "payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?);",
                (
                    event_id,
                    run_id,
                    seq,
                    event_type,
                    _redacted_json(payload or {}),
                    created,
                ),
            )
            return {
                "event_id": event_id,
                "run_id": run_id,
                "seq": seq,
                "event_type": event_type,
                "payload": payload or {},
                "created_at": created,
            }

        if is_generated:
            with active_conn:
                return _do()
        return _do()


def list_events_after(
    run_id: str,
    after_seq: int,
    *,
    limit: int = 200,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict[str, Any]]:
    """Return events with ``seq > after_seq`` in ascending order (SSE replay)."""
    with auto_connection(conn) as (active_conn, _):
        rows = active_conn.execute(
            "SELECT * FROM workflow_events WHERE run_id = ? AND seq > ? "
            "ORDER BY seq ASC LIMIT ?;",
            (run_id, after_seq, limit),
        ).fetchall()
    events = []
    for row in rows:
        event = dict(row)
        event["payload"] = _loads(event.get("payload_json"), {})
        events.append(event)
    return events


def list_events(
    run_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        rows = active_conn.execute(
            "SELECT * FROM workflow_events WHERE run_id = ? ORDER BY seq ASC;",
            (run_id,),
        ).fetchall()
    events = []
    for row in rows:
        event = dict(row)
        event["payload"] = _loads(event.get("payload_json"), {})
        events.append(event)
    return events
