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

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from obsidian_ai_hub.tasks.execution import CANCEL_CERTAINTY_COMPLETED
from obsidian_ai_hub.web.routes.deps import require_bearer_token
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.execution import (
    ATTENTION_REASON_CANCEL_COMPLETED,
    ATTENTION_REASON_CANCEL_UNKNOWN,
)
from obsidian_ai_hub.workflow.capabilities import (
    WORKFLOW_ONLY_KEYS,
    WORKFLOW_ONLY_METADATA,
    default_approval_policy,
    is_workflow_only,
    workflow_capability_keys,
)
from obsidian_ai_hub.workflow.models import (
    RUN_TERMINAL_STATUSES,
    RUN_WAITING_STATUSES,
    validate_value_against_schema,
)
from obsidian_ai_hub.workflow import templates as workflow_templates
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


def _requires_approval(revision: dict[str, Any]) -> bool:
    from obsidian_ai_hub.tasks import store as task_store

    policies = {
        str(c["capability_key"]): str(c.get("approval_policy") or "plan_required")
        for c in task_store.list_capabilities()
    }
    for node in revision.get("nodes") or []:
        node_type = node.get("node_type")
        if node_type == "agent":
            return True
        if node_type != "capability":
            continue
        key = str((node.get("config") or {}).get("capability_key") or "")
        if not key:
            continue
        policy = policies.get(key, default_approval_policy(key))
        if policy == "plan_required":
            return True
    return False


@router.get("")
def list_workflows(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    workflows, total = workflow_store.list_workflows(limit=limit, offset=offset)
    return {"items": workflows, "total": total}


@router.post("", status_code=201)
def create_workflow(payload: WorkflowCreate) -> dict[str, Any]:
    return workflow_store.create_workflow(
        payload.name, payload.description, inputs_schema=payload.inputs_schema
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


@router.get("/capabilities")
def list_workflow_capabilities() -> dict[str, Any]:
    """List capabilities selectable in a Workflow revision.

    Registry-derived capabilities carry their DB enablement/approval policy;
    workflow-only capabilities (``hitl_wait``) are always enabled and auto.
    """
    from obsidian_ai_hub.tasks import store as task_store
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

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
            }
        )
    return {"items": items}


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str) -> dict[str, Any]:
    workflow = workflow_store.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    runs, _ = workflow_store.list_runs(workflow_id=workflow_id, limit=10)
    workflow["revisions"] = workflow_store.list_revisions(workflow_id)
    workflow["runs"] = runs
    return workflow


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


@router.post("/revisions/{revision_id}/runs", status_code=201)
def create_run(revision_id: str, payload: RunCreate) -> dict[str, Any]:
    revision = workflow_store.get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="revision not found")
    input_errors = validate_value_against_schema(
        payload.inputs, revision.get("inputs_schema") or {}, path="run.inputs"
    )
    if input_errors:
        raise HTTPException(status_code=422, detail={"errors": input_errors})
    initial_status = (
        "waiting_approval" if _requires_approval(revision) else "queued"
    )
    try:
        return workflow_store.create_run(
            str(revision["workflow_id"]),
            revision_id,
            payload.inputs,
            initial_status=initial_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
        inputs, snapshot.get("inputs_schema") or {}, path="run.inputs"
    )
    if input_errors:
        raise HTTPException(status_code=422, detail={"errors": input_errors})
    initial_status = (
        "waiting_approval"
        if _requires_approval({"nodes": snapshot.get("nodes") or []})
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
