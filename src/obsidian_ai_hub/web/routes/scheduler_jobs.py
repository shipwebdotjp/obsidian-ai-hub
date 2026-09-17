import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_bearer_token
from obsidian_ai_hub.web.services.scheduler_jobs import SchedulerJobConfigConflictError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/scheduler-jobs/recurring-jobs", response_model=schemas.SchedulerJobConfigResponse)
def get_recurring_jobs(_=Depends(require_bearer_token)):
    try:
        return service.get_recurring_jobs()
    except Exception:
        logger.exception("Failed to get recurring jobs")
        raise HTTPException(status_code=500, detail="Failed to load scheduler jobs")


@router.put("/scheduler-jobs/recurring-jobs", response_model=schemas.SchedulerJobConfigUpdateResponse)
def update_recurring_jobs(
    body: schemas.SchedulerJobConfigRequest,
    _=Depends(require_bearer_token),
):
    try:
        result = service.update_recurring_jobs(body.revision, body.jobs)
    except SchedulerJobConfigConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception:
        logger.exception("Failed to update recurring jobs")
        raise HTTPException(status_code=500, detail="Failed to update scheduler jobs")
    return result


@router.post("/scheduler-jobs/preview", response_model=schemas.CommandPreviewResponse)
def preview_command(
    body: schemas.CommandPreviewRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.preview_command(body.command)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception:
        logger.exception("Failed to preview command")
        raise HTTPException(status_code=500, detail="Failed to preview command")


@router.get("/scheduler-jobs/one-shot-jobs", response_model=schemas.OneShotJobListResponse)
def list_one_shot_jobs(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _=Depends(require_bearer_token),
):
    try:
        return service.list_one_shot_jobs(limit=limit, offset=offset)
    except Exception:
        logger.exception("Failed to list one-shot jobs")
        raise HTTPException(status_code=500, detail="Failed to list one-shot jobs")


@router.get("/scheduler-jobs/one-shot-jobs/{job_id}", response_model=schemas.OneShotJobDetail)
def get_one_shot_job_detail(job_id: str, _=Depends(require_bearer_token)):
    try:
        detail = service.get_one_shot_job_detail(job_id)
    except Exception:
        logger.exception("Failed to get one-shot job detail")
        raise HTTPException(status_code=500, detail="Failed to get one-shot job")
    if detail is None:
        raise HTTPException(status_code=404, detail="One-shot job not found")
    return detail


@router.post("/scheduler-jobs/one-shot-jobs/{job_id}/cancel", response_model=schemas.OneShotJobSummary)
def cancel_one_shot_job(job_id: str, _=Depends(require_bearer_token)):
    try:
        return service.cancel_one_shot_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="One-shot job not found")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception:
        logger.exception("Failed to cancel one-shot job")
        raise HTTPException(status_code=500, detail="Failed to cancel one-shot job")


@router.get("/scheduler-jobs/job-states", response_model=schemas.JobStateListResponse)
def list_job_states(_=Depends(require_bearer_token)):
    try:
        return {"items": service.list_job_states()}
    except Exception:
        logger.exception("Failed to list job states")
        raise HTTPException(status_code=500, detail="Failed to list job states")
