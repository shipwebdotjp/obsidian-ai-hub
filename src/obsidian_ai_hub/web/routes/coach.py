from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from obsidian_ai_hub.coach import (
    CoachDuplicateReflectionError,
    CoachFocusNotFoundError,
    CoachGoalNotFoundError,
    CoachReflectionNotFoundError,
    CoachService,
    CoachStateValidationError,
)
from obsidian_ai_hub.web.routes.deps import require_bearer_token
from obsidian_ai_hub.web.schemas import (
    CoachFocus,
    CoachFocusCreateRequest,
    CoachFocusUpdateRequest,
    CoachGoalCreateRequest,
    CoachGoalDetail,
    CoachGoalListResponse,
    CoachGoalUpdateRequest,
    CoachThreadResponse,
    CoachWeeklyReflection,
    CoachWeeklyReflectionCreateRequest,
    CoachWeeklyReflectionUpdateRequest,
)

router = APIRouter(prefix="/coach", tags=["coach"], dependencies=[Depends(require_bearer_token)])


def get_coach_service() -> CoachService:
    return CoachService()


# --- Goal endpoints ---


@router.get("/goals", response_model=CoachGoalListResponse)
def list_goals(
    status: Optional[str] = Query(None, description="Filter by goal status (active/paused/ended)"),
    service: CoachService = Depends(get_coach_service),
) -> CoachGoalListResponse:
    goals = service.list_goals(status=status)
    return CoachGoalListResponse(items=goals, total=len(goals))


@router.post("/goals", response_model=CoachGoalDetail, status_code=status.HTTP_201_CREATED)
def create_goal(
    req: CoachGoalCreateRequest,
    service: CoachService = Depends(get_coach_service),
) -> CoachGoalDetail:
    try:
        return service.create_goal(
            statement=req.statement,
            reason=req.reason,
            initial_focuses=req.initial_focuses,
        )
    except CoachStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/goals/{goal_id}", response_model=CoachGoalDetail)
def get_goal(
    goal_id: str,
    service: CoachService = Depends(get_coach_service),
) -> CoachGoalDetail:
    try:
        return service.get_goal(goal_id)
    except CoachGoalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/goals/{goal_id}", response_model=CoachGoalDetail)
def update_goal(
    goal_id: str,
    req: CoachGoalUpdateRequest,
    service: CoachService = Depends(get_coach_service),
) -> CoachGoalDetail:
    try:
        return service.update_goal(goal_id, statement=req.statement, reason=req.reason)
    except CoachGoalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CoachStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/goals/{goal_id}/pause", response_model=CoachGoalDetail)
def pause_goal(
    goal_id: str,
    service: CoachService = Depends(get_coach_service),
) -> CoachGoalDetail:
    try:
        return service.pause_goal(goal_id)
    except CoachGoalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CoachStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/goals/{goal_id}/resume", response_model=CoachGoalDetail)
def resume_goal(
    goal_id: str,
    service: CoachService = Depends(get_coach_service),
) -> CoachGoalDetail:
    try:
        return service.resume_goal(goal_id)
    except CoachGoalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CoachStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/goals/{goal_id}/end", response_model=CoachGoalDetail)
def end_goal(
    goal_id: str,
    service: CoachService = Depends(get_coach_service),
) -> CoachGoalDetail:
    try:
        return service.end_goal(goal_id)
    except CoachGoalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CoachStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# --- Focus endpoints ---


@router.post(
    "/goals/{goal_id}/focuses", response_model=CoachFocus, status_code=status.HTTP_201_CREATED
)
def create_focus(
    goal_id: str,
    req: CoachFocusCreateRequest,
    service: CoachService = Depends(get_coach_service),
) -> CoachFocus:
    try:
        return service.create_focus(goal_id, name=req.name)
    except CoachGoalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CoachStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.patch("/focuses/{focus_id}", response_model=CoachFocus)
def update_focus(
    focus_id: str,
    req: CoachFocusUpdateRequest,
    service: CoachService = Depends(get_coach_service),
) -> CoachFocus:
    try:
        return service.update_focus(focus_id, name=req.name)
    except (CoachFocusNotFoundError, CoachGoalNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CoachStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/focuses/{focus_id}/activate", response_model=CoachFocus)
def activate_focus(
    focus_id: str,
    service: CoachService = Depends(get_coach_service),
) -> CoachFocus:
    try:
        return service.activate_focus(focus_id)
    except (CoachFocusNotFoundError, CoachGoalNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CoachStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/focuses/{focus_id}/pause", response_model=CoachFocus)
def pause_focus(
    focus_id: str,
    service: CoachService = Depends(get_coach_service),
) -> CoachFocus:
    try:
        return service.pause_focus(focus_id)
    except (CoachFocusNotFoundError, CoachGoalNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CoachStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# --- Reflection endpoints ---


@router.post(
    "/focuses/{focus_id}/reflections",
    response_model=CoachWeeklyReflection,
    status_code=status.HTTP_201_CREATED,
)
def create_weekly_reflection(
    focus_id: str,
    req: CoachWeeklyReflectionCreateRequest,
    service: CoachService = Depends(get_coach_service),
) -> CoachWeeklyReflection:
    if req.focus_id != focus_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="focus_id in URL does not match focus_id in body",
        )
    try:
        return service.create_weekly_reflection(
            focus_id=focus_id,
            iso_week_monday=req.iso_week_monday,
            worked_well=req.worked_well,
            difficult_reason=req.difficult_reason,
            learnings=req.learnings,
            next_week_scope=req.next_week_scope,
            decision_type=req.decision_type,
            target_focus_id=req.target_focus_id,
        )
    except (CoachFocusNotFoundError, CoachGoalNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CoachStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except CoachDuplicateReflectionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/focuses/{focus_id}/reflections", response_model=list[CoachWeeklyReflection])
def list_reflections_by_focus(
    focus_id: str,
    service: CoachService = Depends(get_coach_service),
) -> list[CoachWeeklyReflection]:
    try:
        return service.list_reflections_by_focus(focus_id)
    except CoachFocusNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/reflections/{reflection_id}", response_model=CoachWeeklyReflection)
def get_reflection(
    reflection_id: str,
    service: CoachService = Depends(get_coach_service),
) -> CoachWeeklyReflection:
    try:
        return service.get_reflection(reflection_id)
    except CoachReflectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/reflections/{reflection_id}", response_model=CoachWeeklyReflection)
def update_reflection(
    reflection_id: str,
    req: CoachWeeklyReflectionUpdateRequest,
    service: CoachService = Depends(get_coach_service),
) -> CoachWeeklyReflection:
    try:
        return service.update_reflection(
            reflection_id,
            worked_well=req.worked_well,
            difficult_reason=req.difficult_reason,
            learnings=req.learnings,
            next_week_scope=req.next_week_scope,
        )
    except CoachReflectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CoachStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# --- Coach Thread endpoints ---


@router.get("/goals/{goal_id}/thread", response_model=CoachThreadResponse)
def list_thread_events(
    goal_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: CoachService = Depends(get_coach_service),
) -> CoachThreadResponse:
    try:
        events, total = service.list_thread_events(goal_id, limit=limit, offset=offset)
        return CoachThreadResponse(items=events, total=total)
    except CoachGoalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
