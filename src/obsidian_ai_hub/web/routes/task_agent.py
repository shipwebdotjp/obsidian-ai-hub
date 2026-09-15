from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_bearer_token

router = APIRouter(prefix="/task-agent", tags=["task-agent"])


@router.get("/tasks", response_model=schemas.TaskAgentListResponse)
def list_tasks(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _=Depends(require_bearer_token),
):
    items, total = service.list_task_agent_tasks(
        status=status, limit=limit, offset=offset
    )
    return {"items": items, "total": total}


@router.post(
    "/tasks", response_model=schemas.TaskAgentTask, status_code=201
)
def create_task(
    body: schemas.CreateTaskRequest, _=Depends(require_bearer_token)
):
    try:
        return service.create_task_agent_task(body.prompt_text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tasks/{task_id}", response_model=schemas.TaskAgentTaskDetail)
def get_task(task_id: str, _=Depends(require_bearer_token)):
    detail = service.get_task_agent_task_detail(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return detail


@router.post("/tasks/{task_id}/approve", response_model=schemas.TaskAgentTask)
def approve_task(task_id: str, _=Depends(require_bearer_token)):
    try:
        return service.approve_task_agent_task(task_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tasks/{task_id}/reject", response_model=schemas.TaskAgentTask)
def reject_task(
    task_id: str,
    body: schemas.RejectTaskRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.reject_task_agent_task(task_id, body.reason)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tasks/{task_id}/cancel", response_model=schemas.TaskAgentTask)
def cancel_task(task_id: str, _=Depends(require_bearer_token)):
    try:
        return service.cancel_task_agent_task(task_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tasks/{task_id}/replan", response_model=schemas.TaskAgentTask)
def replan_task(task_id: str, _=Depends(require_bearer_token)):
    try:
        return service.replan_task_agent_task(task_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/capabilities", response_model=list[schemas.TaskAgentCapability])
def list_capabilities(_=Depends(require_bearer_token)):
    return service.list_task_agent_capabilities()


@router.put(
    "/capabilities/{capability_key}",
    response_model=schemas.TaskAgentCapability,
)
def update_capability(
    capability_key: str,
    body: schemas.CapabilityUpdateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.update_task_agent_capability(
            capability_key,
            enabled=body.enabled,
            approval_policy=body.approval_policy,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
