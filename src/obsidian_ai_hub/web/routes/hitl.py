from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_loopback_or_token

router = APIRouter()


@router.get("/hitl/runs", response_model=schemas.HitlRunListResponse)
def list_hitl_runs(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _=Depends(require_loopback_or_token),
):
    items, total = service.list_hitl_runs(status=status, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/hitl/runs/{run_id}", response_model=schemas.HitlRunDetail)
def get_hitl_run(run_id: str, _=Depends(require_loopback_or_token)):
    detail = service.get_hitl_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail


@router.post("/hitl/runs/{run_id}/questions/{question_key}/answer")
def submit_hitl_answer(
    run_id: str,
    question_key: str,
    body: schemas.SubmitAnswerRequest,
    _=Depends(require_loopback_or_token),
):
    try:
        answer_payload = {"value": body.answer, "comment": body.comment}
        service.submit_hitl_answer(run_id, question_key, answer_payload)
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/hitl/runs/{run_id}/cancel")
def cancel_hitl_run(run_id: str, _=Depends(require_loopback_or_token)):
    try:
        service.cancel_hitl_run(run_id)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
