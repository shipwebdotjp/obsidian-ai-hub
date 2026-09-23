"""Workflow Web API (Phase 1: backend contract).

All endpoints require the shared bearer token (``web/routes/deps.py``).
GUI wiring is a later phase; this module only exposes the store/validation/
engine contract documented in ``docs/workflow/specification.md`` §16.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from obsidian_ai_hub.tasks.execution import CANCEL_CERTAINTY_COMPLETED
from obsidian_ai_hub.web.routes.deps import require_bearer_token
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow import user_templates as workflow_user_templates
from obsidian_ai_hub.workflow import definition_package as workflow_package
from obsidian_ai_hub.workflow.execution import (
    ATTENTION_REASON_CANCEL_COMPLETED,
    ATTENTION_REASON_CANCEL_UNKNOWN,
)
from obsidian_ai_hub.workflow.capabilities import (
    WORKFLOW_ONLY_INPUT_SCHEMA,
    WORKFLOW_ONLY_KEYS,
    WORKFLOW_ONLY_METADATA,
    WORKFLOW_ONLY_OUTPUT_SCHEMA,
    default_approval_policy,
    is_workflow_only,
    workflow_capability_keys,
)
from obsidian_ai_hub.workflow.models import (
    RUN_TERMINAL_STATUSES,
    RUN_WAITING_STATUSES,
    validate_value_against_schema,
)
from obsidian_ai_hub.workflow import scheduling as workflow_scheduling
from obsidian_ai_hub.workflow import templates as workflow_templates
from obsidian_ai_hub.workflow.graph_copy import renumber_graph
from obsidian_ai_hub.workflow.validation import validate_graph

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
    dependencies=[Depends(require_bearer_token)],
)


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    inputs_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    skip_approval: bool = False


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    skip_approval: Optional[bool] = None


class GraphUpdate(BaseModel):
    inputs_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class RunCreate(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class AttentionDecision(BaseModel):
    decision: str = Field(pattern="^(adopt|fail|reexecute|interrupt)$")
    output: Optional[dict[str, Any]] = None


class RerunRequest(BaseModel):
    inputs: Optional[dict[str, Any]] = None


def _capability_enabled() -> Any:
    from obsidian_ai_hub.tasks import store as task_store

    enabled = {
        str(c["capability_key"]): bool(c["enabled"])
        for c in task_store.list_capabilities()
    }
    valid_keys = workflow_capability_keys()
    return lambda key: key in valid_keys and (
        is_workflow_only(key) or enabled.get(key, False)
    )


def _agent_exists() -> Any:
    from obsidian_ai_hub.agents import store as agent_store

    return lambda agent_id: agent_store.get_agent(agent_id) is not None


def _validate_revision(revision: dict[str, Any]) -> list[str]:
    return validate_graph(
        nodes=revision.get("nodes") or [],
        edges=revision.get("edges") or [],
        inputs_schema=revision.get("inputs_schema") or {},
        capability_enabled=_capability_enabled(),
        agent_exists=_agent_exists(),
    )


@router.get("")
def list_workflows(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    workflows, total = workflow_store.list_workflows(limit=limit, offset=offset)
    return {"items": workflows, "total": total}


@router.post("", status_code=201)
def create_workflow(payload: WorkflowCreate) -> dict[str, Any]:
    return workflow_store.create_workflow(
        payload.name,
        payload.description,
        inputs_schema=payload.inputs_schema,
        skip_approval=payload.skip_approval,
    )


class WorkflowFromTemplate(BaseModel):
    template_key: str = Field(min_length=1)
    name: Optional[str] = None
    description: Optional[str] = None


@router.get("/templates")
def list_templates() -> dict[str, Any]:
    return {"items": workflow_templates.list_templates()}


@router.post("/from-template", status_code=201)
def create_from_template(payload: WorkflowFromTemplate) -> dict[str, Any]:
    template = workflow_templates.get_template(payload.template_key)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
    workflow = workflow_store.create_workflow(
        payload.name or template["name"],
        payload.description or template["description"],
        inputs_schema=template["inputs_schema"],
    )
    revision = workflow["revision"]
    nodes, edges = workflow_templates.build_graph(template)
    workflow_store.set_revision_graph(revision["revision_id"], nodes, edges)
    workflow["revision"] = workflow_store.get_revision(revision["revision_id"])
    return workflow


class UserTemplateCreate(BaseModel):
    source_revision_id: str = Field(min_length=1)
    name: Optional[str] = None
    description: Optional[str] = None


class UserTemplateUpdate(BaseModel):
    source_revision_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


class UserTemplateInstantiate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


def _safe_filename(name: str) -> str:
    cleaned = "".join(
        ch if (ch.isascii() and (ch.isalnum() or ch in ("-", "_", "."))) else "-"
        for ch in (name or "").strip()
    ).strip("-")
    return cleaned or "workflow-definition"


def _package_response(text: str, fmt: str, filename: str) -> Response:
    media_type = "application/json" if fmt == "json" else "application/x-yaml"
    disposition = (
        f'attachment; filename="{_safe_filename(filename)}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )
    return Response(
        content=text,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


def _import_result(workflow: dict[str, Any]) -> dict[str, Any]:
    revision = workflow["revision"]
    return {
        "workflow": workflow,
        "revision": revision,
        "validation_errors": _validate_revision(revision),
    }


@router.get("/user-templates")
def list_user_templates() -> dict[str, Any]:
    return {"items": workflow_user_templates.list_user_templates()}


@router.post("/user-templates", status_code=201)
def create_user_template(payload: UserTemplateCreate) -> dict[str, Any]:
    try:
        return workflow_user_templates.create_user_template(
            payload.source_revision_id, payload.name, payload.description
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/user-templates/{template_id}")
def get_user_template(template_id: str) -> dict[str, Any]:
    template = workflow_user_templates.get_user_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
    return template


@router.put("/user-templates/{template_id}")
def update_user_template(
    template_id: str, payload: UserTemplateUpdate
) -> dict[str, Any]:
    try:
        return workflow_user_templates.update_user_template(
            template_id,
            source_revision_id=payload.source_revision_id,
            name=payload.name,
            description=payload.description,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/user-templates/{template_id}")
def delete_user_template(template_id: str) -> dict[str, Any]:
    try:
        workflow_user_templates.delete_user_template(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "template_id": template_id}


@router.post("/user-templates/{template_id}/instantiate", status_code=201)
def instantiate_user_template(
    template_id: str, payload: UserTemplateInstantiate
) -> dict[str, Any]:
    try:
        workflow = workflow_user_templates.instantiate_user_template(
            template_id, payload.name, payload.description
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _import_result(workflow)


@router.get("/user-templates/{template_id}/export")
def export_user_template(
    template_id: str, format: str = Query("json", pattern="^(json|yaml)$")
) -> Response:
    template = workflow_user_templates.get_user_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
    text = workflow_package.serialize_package(template["definition"], format)
    filename = f"{template['name']}.{format}"
    return _package_response(text, format, filename)


@router.post("/import", status_code=201)
async def import_workflow(
    request: Request, format: str = Query("json", pattern="^(json|yaml)$")
) -> dict[str, Any]:
    """Import a definition package as a new workflow + draft revision.

    Structural boundary violations stop with 422 before any DB write. A package
    that parses but fails graph validation still creates the draft so the user
    can fix it in the editor (it is never published or run automatically).
    The SQLite work is offloaded so the event loop is not blocked.
    """
    raw = await request.body()
    return await run_in_threadpool(_import_definition_package, raw, format)


def _import_definition_package(raw: bytes, format: str) -> dict[str, Any]:
    try:
        package = workflow_package.parse_package(raw, format)
    except workflow_package.DefinitionPackageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    nodes, edges = workflow_package.package_to_graph(package)
    new_nodes, new_edges = renumber_graph(nodes, edges)
    workflow = workflow_store.create_workflow_from_graph(
        package["name"],
        package["description"],
        package["inputs_schema"],
        new_nodes,
        new_edges,
    )
    return _import_result(workflow)


@router.get("/capabilities")
def list_workflow_capabilities() -> dict[str, Any]:
    """List capabilities selectable in a Workflow revision.

    Registry-derived capabilities carry their DB enablement/approval policy;
    workflow-only capabilities (``hitl_wait``) are always enabled and auto.
    """
    from obsidian_ai_hub.tasks import store as task_store
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions
    from obsidian_ai_hub.tasks.capability_schemas import (
        ui_input_schema,
        ui_output_schema,
        ui_target_schema,
    )

    policies = {
        str(c["capability_key"]): c for c in task_store.list_capabilities()
    }
    items: list[dict[str, Any]] = []
    for definition in get_capability_definitions():
        record = policies.get(definition.key, {})
        items.append(
            {
                "capability_key": definition.key,
                "label": definition.label,
                "description": definition.description,
                "enabled": bool(record.get("enabled", False)),
                "approval_policy": str(
                    record.get("approval_policy")
                    or default_approval_policy(definition.key)
                ),
                "workflow_only": False,
                "inputs_schema": ui_input_schema(definition.key),
                "target_schema": ui_target_schema(definition.key),
                "output_schema": ui_output_schema(definition.key),
            }
        )
    for key in sorted(WORKFLOW_ONLY_KEYS):
        label, description = WORKFLOW_ONLY_METADATA.get(key, (key, ""))
        items.append(
            {
                "capability_key": key,
                "label": label,
                "description": description,
                "enabled": True,
                "approval_policy": default_approval_policy(key),
                "workflow_only": True,
                "inputs_schema": WORKFLOW_ONLY_INPUT_SCHEMA.get(key),
                "target_schema": None,
                "output_schema": WORKFLOW_ONLY_OUTPUT_SCHEMA.get(key),
            }
        )
    return {"items": items}


@router.get("/schedulable")
def list_schedulable_workflows() -> dict[str, Any]:
    """List workflows with a published revision for Scheduler Job targeting."""
    items = workflow_store.list_schedulable_workflows()
    return {"items": items, "total": len(items)}


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str) -> dict[str, Any]:
    workflow = workflow_store.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    runs, _ = workflow_store.list_runs(workflow_id=workflow_id, limit=10)
    workflow["revisions"] = workflow_store.list_revisions(workflow_id)
    workflow["runs"] = runs
    return workflow


@router.patch("/{workflow_id}")
def update_workflow(workflow_id: str, payload: WorkflowUpdate) -> dict[str, Any]:
    """Partially update a workflow's name, description and approval skip."""
    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] is None:
        raise HTTPException(status_code=422, detail="name must not be null")
    if "description" in fields and fields["description"] is None:
        fields["description"] = ""
    if "skip_approval" in fields and fields["skip_approval"] is None:
        raise HTTPException(status_code=422, detail="skip_approval must not be null")
    try:
        return workflow_store.update_workflow(
            workflow_id,
            name=fields.get("name"),
            description=fields.get("description"),
            skip_approval=fields.get("skip_approval"),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: str) -> dict[str, Any]:
    """Delete a workflow and its whole aggregate (definition and run history).

    Rejected with 409 when a Scheduler Job still targets the workflow or a
    non-terminal run exists; both leave no way to reach the run afterwards.
    """
    if workflow_store.get_workflow(workflow_id) is None:
        raise HTTPException(
            status_code=404, detail=f"Workflow '{workflow_id}' not found."
        )
    references = _scheduler_references(workflow_id)
    if references:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Scheduler Job がこの Workflow を参照しています。"
                    "先に対象を変更または削除してください。"
                ),
                "references": references,
            },
        )
    try:
        deleted = workflow_store.delete_workflow(workflow_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "workflow_id": workflow_id, "deleted": deleted}


def _scheduler_references(workflow_id: str) -> list[dict[str, str]]:
    """Return Scheduler Jobs (recurring and one-shot) targeting the workflow."""
    from obsidian_ai_hub.scheduler_jobs import one_shot as one_shot_store
    from obsidian_ai_hub.scheduler_jobs import recurring

    references: list[dict[str, str]] = []
    for job in recurring.load_jobs() or []:
        target = recurring.get_workflow_target(job)
        if target and str(target.get("workflow_id") or "") == workflow_id:
            references.append(
                {"source": "recurring", "job_id": str((job or {}).get("id") or "")}
            )
    for job in one_shot_store.find_non_terminal_workflow_jobs(workflow_id):
        references.append(
            {"source": "one_shot", "job_id": str(job.get("job_id") or "")}
        )
    return references


@router.post("/{workflow_id}/revisions", status_code=201)
def create_revision(workflow_id: str) -> dict[str, Any]:
    """Create the next draft revision for further editing.

    When the workflow has a published revision, its graph and inputs_schema
    are copied into the new draft (fresh ids, source left immutable). With no
    published revision the draft starts blank.
    """
    workflow = workflow_store.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    return workflow_store.create_revision(workflow_id)


@router.get("/revisions/{revision_id}")
def get_revision(revision_id: str) -> dict[str, Any]:
    revision = workflow_store.get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="revision not found")
    return revision


@router.get("/revisions/{revision_id}/export")
def export_revision(
    revision_id: str, format: str = Query("json", pattern="^(json|yaml)$")
) -> Response:
    """Export a published revision's definition as a package (draft rejected)."""
    revision = workflow_store.get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="revision not found")
    if str(revision["status"]) != "published":
        raise HTTPException(
            status_code=409,
            detail="Only a published revision can be exported.",
        )
    workflow = workflow_store.get_workflow(str(revision["workflow_id"]))
    assert workflow is not None
    package = workflow_package.build_package(
        str(workflow["name"]),
        str(workflow.get("description") or ""),
        revision.get("inputs_schema") or {"type": "object"},
        revision.get("nodes") or [],
        revision.get("edges") or [],
    )
    text = workflow_package.serialize_package(package, format)
    filename = f"{workflow['name']}-v{revision.get('version')}.{format}"
    return _package_response(text, format, filename)


@router.put("/revisions/{revision_id}")
def update_revision(revision_id: str, payload: GraphUpdate) -> dict[str, Any]:
    try:
        workflow_store.update_revision_schema(revision_id, payload.inputs_schema)
        workflow_store.set_revision_graph(
            revision_id, payload.nodes, payload.edges
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, TypeError, sqlite3.IntegrityError) as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid graph payload: {exc}"
        ) from exc
    revision = workflow_store.get_revision(revision_id)
    assert revision is not None
    return revision


@router.post("/revisions/{revision_id}/validate")
def validate_revision(revision_id: str) -> dict[str, Any]:
    revision = workflow_store.get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="revision not found")
    errors = _validate_revision(revision)
    return {"valid": not errors, "errors": errors}


@router.post("/revisions/{revision_id}/publish")
def publish_revision(revision_id: str) -> dict[str, Any]:
    revision = workflow_store.get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="revision not found")
    errors = _validate_revision(revision)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    try:
        return workflow_store.publish_revision(revision_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/revisions/{revision_id}")
def delete_revision(revision_id: str) -> dict[str, Any]:
    """Delete a draft or superseded revision with its graph.

    Published revisions are rejected; runs referencing the deleted
    revision are kept (they carry their own graph snapshot).
    """
    try:
        workflow_store.delete_revision(revision_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "revision_id": revision_id}


def _record_approval_skip_if_needed(
    run_id: str,
    nodes: list[dict[str, Any]],
    *,
    skip_approval: bool,
) -> None:
    """Audit a run that bypassed the approval gate it would otherwise need."""
    if skip_approval and workflow_scheduling.requires_approval(nodes):
        workflow_store.append_event(
            run_id,
            "run_approval_skipped",
            {"reason": "workflow_skip_approval"},
        )


@router.post("/revisions/{revision_id}/runs", status_code=201)
def create_run(revision_id: str, payload: RunCreate) -> dict[str, Any]:
    revision = workflow_store.get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="revision not found")
    input_errors = validate_value_against_schema(
        payload.inputs,
        revision.get("inputs_schema") or {},
        path="run.inputs",
        allow_expressions=True,
    )
    if input_errors:
        raise HTTPException(status_code=422, detail={"errors": input_errors})
    nodes = revision.get("nodes") or []
    skip_approval = workflow_store.workflow_skip_approval(
        str(revision["workflow_id"])
    )
    initial_status = (
        "waiting_approval"
        if workflow_scheduling.requires_approval(
            nodes, skip_approval=skip_approval
        )
        else "queued"
    )
    try:
        run = workflow_store.create_run(
            str(revision["workflow_id"]),
            revision_id,
            payload.inputs,
            initial_status=initial_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _record_approval_skip_if_needed(
        str(run["run_id"]), nodes, skip_approval=skip_approval
    )
    return run


@router.post("/runs/{run_id}/rerun", status_code=201)
def rerun_run(run_id: str, payload: RerunRequest) -> dict[str, Any]:
    """Create a new run from a terminal run's snapshot (inputs overridable).

    Uses the stored graph snapshot, so the rerun works even when the source
    revision has been superseded. ``source_run_id`` links the lineage.
    """
    source = workflow_store.get_run(run_id)
    if source is None:
        raise HTTPException(status_code=404, detail="run not found")
    if str(source["status"]) not in RUN_TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409, detail="only a terminal run can be rerun"
        )
    snapshot = source.get("graph_snapshot") or {}
    inputs = (
        dict(payload.inputs)
        if payload.inputs is not None
        else dict(source.get("inputs") or {})
    )
    input_errors = validate_value_against_schema(
        inputs,
        snapshot.get("inputs_schema") or {},
        path="run.inputs",
        allow_expressions=True,
    )
    if input_errors:
        raise HTTPException(status_code=422, detail={"errors": input_errors})
    nodes = snapshot.get("nodes") or []
    skip_approval = workflow_store.workflow_skip_approval(
        str(source["workflow_id"])
    )
    initial_status = (
        "waiting_approval"
        if workflow_scheduling.requires_approval(
            nodes, skip_approval=skip_approval
        )
        else "queued"
    )
    new_run = workflow_store.create_rerun_run(
        source, inputs, initial_status=initial_status
    )
    workflow_store.append_event(
        str(new_run["run_id"]),
        "run_rerun_created",
        {"source_run_id": run_id},
    )
    _record_approval_skip_if_needed(
        str(new_run["run_id"]), nodes, skip_approval=skip_approval
    )
    return new_run


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = workflow_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    run["nodes"] = workflow_store.list_run_nodes(run_id)
    run["events"] = workflow_store.list_events(run_id)
    return run


@router.post("/runs/{run_id}/approve")
def approve_run(run_id: str) -> dict[str, Any]:
    return _transition(run_id, "queued", from_status="waiting_approval")


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    """Request cancellation (not a rollback).

    Waiting/queued runs stop immediately; a running run records ``cancelling``
    together with a cancel event and marks any in-flight bridge Task
    ``cancelling`` so the adapter can stop its child run. A ``waiting_hitl``
    run also cancels the linked HITL run so a late answer cannot requeue it.
    """
    run = workflow_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    try:
        updated = workflow_store.request_run_cancel(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    targets = workflow_store.list_cancel_targets(run_id)
    _cancel_bridge_tasks(targets["bridge_task_ids"])
    for hitl_run_id in targets["hitl_run_ids"]:
        _cancel_hitl_run(hitl_run_id)
    return updated


def _cancel_bridge_tasks(bridge_task_ids: list[str]) -> None:
    from obsidian_ai_hub.tasks import store as task_store

    for bridge_id in bridge_task_ids:
        try:
            task = task_store.get_task(bridge_id)
            if task is None:
                continue
            status = str(task.get("status"))
            if status in task_store.TASK_TERMINAL_STATUSES:
                continue
            if status == "running":
                task_store.transition_task_status(bridge_id, "cancelling")
        except Exception:  # noqa: BLE001 - best-effort; engine also stops
            _logger.warning(
                "Failed to request cancel on bridge task %s", bridge_id, exc_info=True
            )


def _cancel_hitl_run(hitl_run_id: str) -> None:
    try:
        from obsidian_ai_hub.hitl import service as hitl_service

        hitl_service.cancel_run(hitl_run_id)
    except Exception:  # noqa: BLE001 - best-effort; handler checks run status
        _logger.warning(
            "Failed to cancel linked HITL run %s", hitl_run_id, exc_info=True
        )


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: str) -> dict[str, Any]:
    return _transition(run_id, "queued", from_status="interrupted")


@router.post("/runs/{run_id}/attention")
def resolve_attention(run_id: str, payload: AttentionDecision) -> dict[str, Any]:
    run = workflow_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    run_id_str = str(run["run_id"])
    if str(run["status"]) != "waiting_attention":
        raise HTTPException(status_code=409, detail="run is not waiting_attention")
    target: Optional[dict[str, Any]] = None
    for node in workflow_store.list_run_nodes(run_id_str):
        if str(node["status"]) == "needs_attention":
            if target is not None:
                raise HTTPException(
                    status_code=409, detail="multiple nodes need attention"
                )
            target = node
    if target is None:
        raise HTTPException(status_code=409, detail="no node needs attention")
    node_id = str(target["node_id"])
    decision = payload.decision
    if decision == "adopt" and _is_cancel_origin(target):
        if not _has_success_evidence(target):
            raise HTTPException(
                status_code=409,
                detail=(
                    "取消起因の要確認です。保存済みの成功出力・効果の証跡がない"
                    "ため採用できません。失敗として処理・中断・再実行のいずれかを"
                    "選んでください。"
                ),
            )
    workflow_store.append_event(
        run_id_str,
        "attention_resolved",
        {
            "node_id": node_id,
            "activation_id": str(target["activation_id"]),
            "decision": decision,
            "output": payload.output,
        },
    )
    if decision in ("adopt", "reexecute"):
        return _transition(run_id_str, "queued", from_status="waiting_attention")
    if decision == "fail":
        return _transition(run_id_str, "failed", from_status="waiting_attention")
    return _transition(run_id_str, "interrupted", from_status="waiting_attention")


@router.get("/runs/{run_id}/stream")
async def stream_run_events(
    run_id: str,
    request: Request,
    _=Depends(require_bearer_token),
    last_event_id: Optional[str] = Query(default=None, alias="last_event_id"),
    last_event_id_header: Optional[str] = Header(default=None, alias="Last-Event-ID"),
):
    """Replay workflow events after the cursor, then follow until paused/terminal."""
    from obsidian_ai_hub.runs.events import (
        format_sse,
        heartbeat_sse,
        parse_last_event_id,
    )

    if workflow_store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    raw_cursor = (
        last_event_id_header if last_event_id_header is not None else last_event_id
    )
    cursor = parse_last_event_id(raw_cursor)

    async def event_gen():
        nonlocal cursor
        idle_cycles = 0
        try:
            while True:
                if await request.is_disconnected():
                    break
                events = await asyncio.to_thread(
                    workflow_store.list_events_after, run_id, cursor, limit=200
                )
                for event in events:
                    seq = int(event["seq"])
                    payload = dict(event.get("payload") or {})
                    payload.setdefault("event", event.get("event_type"))
                    yield format_sse(seq, payload)
                    cursor = seq
                batch_full = len(events) >= 200
                current = await asyncio.to_thread(workflow_store.get_run, run_id)
                status = str(current["status"]) if current is not None else ""
                # Only close once the backlog is fully drained; a full batch
                # means more real events are waiting.
                if not batch_full and status in (
                    RUN_TERMINAL_STATUSES | RUN_WAITING_STATUSES
                ):
                    return
                if not events:
                    idle_cycles += 1
                    if idle_cycles >= 30:
                        idle_cycles = 0
                        yield heartbeat_sse()
                else:
                    idle_cycles = 0
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/runs/{run_id}/events")
def list_events(run_id: str) -> dict[str, Any]:
    if workflow_store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"items": workflow_store.list_events(run_id)}


_CANCEL_ATTENTION_REASONS = frozenset(
    {ATTENTION_REASON_CANCEL_COMPLETED, ATTENTION_REASON_CANCEL_UNKNOWN}
)


def _is_cancel_origin(node: dict[str, Any]) -> bool:
    return str(node.get("attention_reason") or "") in _CANCEL_ATTENTION_REASONS


def _has_success_evidence(node: dict[str, Any]) -> bool:
    """True when a cancelled external process left verifiable success output."""
    if str(node.get("cancel_outcome") or "") != CANCEL_CERTAINTY_COMPLETED:
        return False
    output = node.get("output")
    effects = node.get("effects") or []
    return bool(output) or bool(effects)


def _transition(
    run_id: str, to_status: str, *, from_status: Optional[str] = None
) -> dict[str, Any]:
    run = workflow_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if from_status is not None and str(run["status"]) != from_status:
        raise HTTPException(status_code=409, detail=f"run is not {from_status}")
    try:
        return workflow_store.transition_run_status(run_id, to_status)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
