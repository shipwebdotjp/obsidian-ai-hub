"""User-managed workflow templates.

A user template is an independent snapshot of a published revision's
definition. It holds no foreign key to the source, so it remains usable after
the origin workflow is deleted, and instantiating it always creates a brand new
workflow with a draft revision (never runs, publishes or schedules anything).
See ``docs/workflow/specification.md`` §16.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.definition_package import (
    build_package,
    package_to_graph,
)
from obsidian_ai_hub.workflow.graph_copy import renumber_graph

_SUMMARY_COLUMNS = (
    "template_id",
    "name",
    "description",
    "source_workflow_id",
    "source_revision_id",
    "created_at",
    "updated_at",
)


def _now_iso() -> str:
    return workflow_store._now_iso()


def _new_id(prefix: str) -> str:
    return workflow_store._new_id(prefix)


def _redacted_json(value: Any) -> str:
    return workflow_store._redacted_json(value)


def _loads(value: Any, default: Any) -> Any:
    return workflow_store._loads(value, default)


def _require_published_revision(
    conn: sqlite3.Connection, revision_id: str
) -> dict[str, Any]:
    revision = workflow_store.get_revision(revision_id, conn=conn)
    if revision is None:
        raise FileNotFoundError(f"Revision '{revision_id}' not found.")
    if str(revision["status"]) != "published":
        raise ValueError(
            f"Revision '{revision_id}' is not published; only a published "
            "revision can be snapshotted."
        )
    return revision


def _build_definition(
    revision: dict[str, Any],
    name: str,
    description: str,
) -> dict[str, Any]:
    return build_package(
        name,
        description,
        revision.get("inputs_schema") or {"type": "object"},
        revision.get("nodes") or [],
        revision.get("edges") or [],
    )


def _template_record(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    record["definition"] = _loads(record.pop("definition_json", None), {})
    return record


def create_user_template(
    source_revision_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Snapshot a published revision into a new user template."""
    template_id: str | None = None
    with workflow_store.auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            nonlocal template_id
            revision = _require_published_revision(active_conn, source_revision_id)
            source_workflow = workflow_store.get_workflow(
                str(revision["workflow_id"]), conn=active_conn
            )
            resolved_name = (name or "").strip() or (
                str(source_workflow["name"]) if source_workflow else "テンプレート"
            )
            definition = _build_definition(
                revision, resolved_name, description or ""
            )
            template_id = _new_id("wtpl")
            now = _now_iso()
            active_conn.execute(
                "INSERT INTO workflow_user_templates (template_id, name, "
                "description, source_workflow_id, source_revision_id, "
                "definition_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    template_id,
                    resolved_name,
                    description or "",
                    str(revision["workflow_id"]),
                    source_revision_id,
                    _redacted_json(definition),
                    now,
                    now,
                ),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
    created = get_user_template(str(template_id), conn=conn)
    assert created is not None
    return created


def list_user_templates(
    *, conn: Optional[sqlite3.Connection] = None
) -> list[dict[str, Any]]:
    with workflow_store.auto_connection(conn) as (active_conn, _):
        rows = active_conn.execute(
            f"SELECT {', '.join(_SUMMARY_COLUMNS)} FROM workflow_user_templates "
            "ORDER BY created_at DESC;"
        ).fetchall()
    return [dict(row) for row in rows]


def get_user_template(
    template_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict[str, Any]]:
    with workflow_store.auto_connection(conn) as (active_conn, _):
        row = active_conn.execute(
            "SELECT * FROM workflow_user_templates WHERE template_id = ?;",
            (template_id,),
        ).fetchone()
    return _template_record(row) if row is not None else None


def update_user_template(
    template_id: str,
    *,
    source_revision_id: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Rename a template and/or replace its definition from a published revision.

    Replacing the definition never touches workflows previously created from
    this template: those carry their own graph copy.
    """
    with workflow_store.auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            row = active_conn.execute(
                "SELECT * FROM workflow_user_templates WHERE template_id = ?;",
                (template_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"Template '{template_id}' not found.")
            existing = _template_record(row)
            resolved_name = existing["name"]
            if name is not None:
                if not name.strip():
                    raise ValueError("template name must not be blank")
                resolved_name = name.strip()
            resolved_description = (
                description if description is not None else existing["description"] or ""
            )
            if source_revision_id is not None:
                revision = _require_published_revision(
                    active_conn, source_revision_id
                )
                definition = _build_definition(
                    revision, resolved_name, resolved_description
                )
                source_workflow_id = str(revision["workflow_id"])
            else:
                definition = existing["definition"]
                definition["name"] = resolved_name
                definition["description"] = resolved_description
                source_workflow_id = existing["source_workflow_id"]
            active_conn.execute(
                "UPDATE workflow_user_templates SET name = ?, description = ?, "
                "source_workflow_id = ?, source_revision_id = ?, "
                "definition_json = ?, updated_at = ? WHERE template_id = ?;",
                (
                    resolved_name,
                    resolved_description,
                    source_workflow_id,
                    source_revision_id or existing["source_revision_id"],
                    _redacted_json(definition),
                    _now_iso(),
                    template_id,
                ),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
    updated = get_user_template(template_id, conn=conn)
    assert updated is not None
    return updated


def delete_user_template(
    template_id: str, *, conn: Optional[sqlite3.Connection] = None
) -> None:
    """Delete only the template row; generated workflows/runs are untouched."""
    with workflow_store.auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            cur = active_conn.execute(
                "DELETE FROM workflow_user_templates WHERE template_id = ?;",
                (template_id,),
            )
            if cur.rowcount == 0:
                raise FileNotFoundError(f"Template '{template_id}' not found.")

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()


def instantiate_user_template(
    template_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Create a new workflow + draft revision from a template snapshot.

    All node/edge ids are renumbered; the template and any previously created
    workflows are left unchanged. No run, publish or scheduler registration.
    """
    template = get_user_template(template_id, conn=conn)
    if template is None:
        raise FileNotFoundError(f"Template '{template_id}' not found.")
    package = template["definition"]
    nodes, edges = package_to_graph(package)
    new_nodes, new_edges = renumber_graph(nodes, edges)
    return workflow_store.create_workflow_from_graph(
        (name or "").strip() or str(package.get("name") or "テンプレート"),
        description if description is not None else str(package.get("description") or ""),
        package.get("inputs_schema") or {"type": "object"},
        new_nodes,
        new_edges,
        conn=conn,
    )
