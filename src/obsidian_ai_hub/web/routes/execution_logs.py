from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_loopback_or_token

router = APIRouter()


@router.get("/execution-logs", response_model=schemas.ExecutionLogListResponse)
def get_execution_logs(
    kind: Optional[str] = None,
    status: Optional[str] = None,
    command: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _=Depends(require_loopback_or_token),
):
    return service.list_execution_logs(
        kind=kind,
        status=status,
        command=command,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


@router.get("/execution-logs/commands/{run_id}", response_model=schemas.CommandRunDetail)
def get_command_run_detail(run_id: str, _=Depends(require_loopback_or_token)):
    detail = service.get_command_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Command run not found")
    return detail


@router.get("/execution-logs/llm/{call_id}", response_model=schemas.LLMCallDetail)
def get_llm_call_detail(call_id: str, _=Depends(require_loopback_or_token)):
    detail = service.get_llm_call_detail(call_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="LLM call not found")
    return detail
