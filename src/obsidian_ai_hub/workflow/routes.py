"""Workflow Web API (Phase 1: backend contract).

All endpoints require the shared bearer token (``web/routes/deps.py``).
GUI wiring is a later phase; this module only exposes the store/validation/
engine contract documented in ``docs/workflow/specification.md`` §16.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from obsidian_ai_hub.web.routes.deps import require_bearer_token
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.capabilities import (
    WORKFLOW_ONLY_KEYS,
    WORKFLOW_ONLY_METADATA,
    default_approval_policy,
    is_workflow_only,
    workflow_capability_keys,
)
from obsidian_ai_hub.workflow.models import validate_value_against_schema
from obsidian_ai_hub.workflow.validation import validate_graph

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
    """Create an empty draft for further editing.

    v1 starts a new draft blank (no graph/inputs_schema clone); the author
    rebuilds or adjusts from a blank canvas. See specification §5.
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
    run = workflow_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    status = str(run["status"])
    if status in ("queued", "waiting_approval", "waiting_hitl", "waiting_attention"):
        return _transition(run_id, "cancelled")
    if status == "running":
        return _transition(run_id, "cancelling")
    raise HTTPException(status_code=409, detail=f"cannot cancel from '{status}'")


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


@router.get("/runs/{run_id}/events")
def list_events(run_id: str) -> dict[str, Any]:
    if workflow_store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"items": workflow_store.list_events(run_id)}


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
