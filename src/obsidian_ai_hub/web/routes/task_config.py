import logging

from fastapi import APIRouter, Depends, HTTPException, status

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_localhost

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/task-config", response_model=schemas.TaskConfigResponse)
def get_task_config(_=Depends(require_localhost)):
    try:
        return service.get_task_config()
    except Exception:
        logger.exception("Failed to get task config")
        raise HTTPException(status_code=500, detail="Failed to load task config")


@router.put("/task-config", response_model=schemas.TaskConfigUpdateResponse)
def update_task_config(
    body: schemas.TaskConfigRequest,
    _=Depends(require_localhost),
):
    try:
        return service.update_task_config(body.revision, body.tasks)
    except service.TaskConfigConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception:
        logger.exception("Failed to update task config")
        raise HTTPException(status_code=500, detail="Failed to update task config")


@router.post("/task-config/preview", response_model=schemas.CommandPreviewResponse)
def preview_command(
    body: schemas.CommandPreviewRequest,
    _=Depends(require_localhost),
):
    try:
        return service.preview_command(body.command)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception:
        logger.exception("Failed to preview command")
        raise HTTPException(status_code=500, detail="Failed to preview command")
