import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/research-themes", response_model=schemas.ResearchThemeListResponse)
def list_research_themes(
    status: Optional[str] = Query(None),
    job_status: Optional[str] = Query(None, alias="job_status"),
    q: Optional[str] = None,
    _=Depends(require_bearer_token),
):
    if status and status not in schemas.ALLOWED_RESEARCH_THEME_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(schemas.ALLOWED_RESEARCH_THEME_STATUS)}",
        )
    if job_status and job_status not in schemas.ALLOWED_RESEARCH_JOB_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"job_status must be one of {sorted(schemas.ALLOWED_RESEARCH_JOB_STATUS)}",
        )
    items = service.list_research_themes(status=status, job_status=job_status, q=q)
    return schemas.ResearchThemeListResponse(items=items, total=len(items))


@router.get("/research-themes/{theme_id}", response_model=schemas.ResearchTheme)
def get_research_theme(theme_id: str, _=Depends(require_bearer_token)):
    item = service.get_research_theme(theme_id)
    if item is None:
        raise HTTPException(status_code=404, detail="research theme not found")
    return item


@router.post("/research-themes/{theme_id}/rerun", response_model=schemas.ResearchJob)
def rerun_research_theme(theme_id: str, _=Depends(require_bearer_token)):
    job = service.rerun_research_theme(theme_id)
    if job is None:
        raise HTTPException(status_code=404, detail="research theme not found")
    return job


@router.post(
    "/research-themes/run",
    response_model=schemas.ResearchRunAcceptedResponse,
    status_code=202,
)
def run_research_theme(
    body: schemas.ResearchRunRequest,
    _=Depends(require_bearer_token),
):
    if not body.theme or not body.theme.strip():
        raise HTTPException(status_code=400, detail="Theme must not be empty or blank")
    try:
        theme_rec, job_rec = service.run_research_theme(
            theme=body.theme,
            mode=body.mode,
        )
        return {"theme": theme_rec, "job": job_rec}
    except ValueError as e:
        logger.warning("Research run validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Failed to start research background job")
        raise HTTPException(
            status_code=500, detail="Failed to start research background job"
        )
