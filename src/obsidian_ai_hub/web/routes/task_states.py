from fastapi import APIRouter, Depends

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_bearer_token

router = APIRouter()


@router.get("/task-states", response_model=schemas.TaskStateListResponse)
def get_task_states(_=Depends(require_bearer_token)):
    return {"items": service.list_task_states()}