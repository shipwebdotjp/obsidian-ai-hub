from datetime import date
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_bearer_token

router = APIRouter()

logger = logging.getLogger(__name__)

MAX_TIMELINE_RANGE_DAYS = 90


@router.get("/planner/timeline", response_model=schemas.PlannerTimelineResponse)
def get_planner_timeline(
    start: date = Query(..., description="Range start (YYYY-MM-DD)"),
    end: date = Query(..., description="Range end (YYYY-MM-DD)"),
    _=Depends(require_bearer_token),
):
    if start > end:
        raise HTTPException(status_code=400, detail="start must be <= end")
    if (end - start).days > MAX_TIMELINE_RANGE_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"range must be <= {MAX_TIMELINE_RANGE_DAYS} days",
        )
    return service.get_planner_timeline(start, end)


@router.get("/planner/proposals", response_model=schemas.PlannerProposalListResponse)
def list_planner_proposals(
    status: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _=Depends(require_bearer_token),
):
    try:
        items, total = service.list_planner_proposals(
            status=status, kind=kind, limit=limit, offset=offset
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"items": items, "total": total}


@router.get("/planner/proposals/{proposal_id}", response_model=schemas.PlannerProposal)
def get_planner_proposal(proposal_id: str, _=Depends(require_bearer_token)):
    proposal = service.get_planner_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@router.patch(
    "/planner/proposals/{proposal_id}", response_model=schemas.PlannerProposal
)
def update_planner_proposal(
    proposal_id: str,
    body: schemas.PlannerProposalUpdateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.update_planner_proposal(
            proposal_id, body.model_dump(exclude_none=True)
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/planner/proposals/{proposal_id}/reject", response_model=schemas.PlannerProposal
)
def reject_planner_proposal(
    proposal_id: str,
    _body: Optional[schemas.PlannerRejectRequest] = None,
    _=Depends(require_bearer_token),
):
    try:
        return service.reject_planner_proposal(
            proposal_id, _body.reason if _body else None
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/planner/proposals/{proposal_id}/promote", response_model=schemas.PlannerProposal
)
def promote_planner_proposal(proposal_id: str, _=Depends(require_bearer_token)):
    try:
        return service.promote_planner_proposal(proposal_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/planner/generate", response_model=schemas.PlannerGenerateResponse)
def generate_planner_proposals(_=Depends(require_bearer_token)):
    try:
        proposals = service.generate_planner_proposals()
    except Exception:
        logger.exception("Planner proposal generation failed")
        raise HTTPException(status_code=500, detail="Proposal generation failed")
    return {"generated": len(proposals), "proposals": proposals}