import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_localhost

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/task-config", response_model=schemas.TaskConfigResponse)
def get_task_config(
    request: Request,
    _=Depends(require_localhost),
):
    try:
        return service.get_task_config()
    except Exception as e:
        logger.exception("Failed to get task config")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/task-config", response_model=schemas.TaskConfigUpdateResponse)
def update_task_config(
    request: Request,
    body: schemas.TaskConfigRequest,
    _=Depends(require_localhost),
):
    try:
        return service.update_task_config(body.revision, body.tasks)
    except service.TaskConfigConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update task config")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/task-config/preview", response_model=schemas.CommandPreviewResponse)
def preview_command(
    request: Request,
    body: schemas.CommandPreviewRequest,
    _=Depends(require_localhost),
):
    try:
        return service.preview_command(body.command)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.exception("Failed to preview command")
        raise HTTPException(status_code=500, detail=str(e))
