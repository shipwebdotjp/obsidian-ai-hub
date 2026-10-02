"""REST API routes for Recurring Events domain (定期記録・リマインダー)."""

from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from obsidian_ai_hub.web.routes.deps import require_bearer_token
from obsidian_ai_hub.web.services import recurring_events as re_service

router = APIRouter()


# --- Pydantic Schemas ---

class PropertyOptionInput(BaseModel):
    option_key: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)


class PropertyDefinitionInput(BaseModel):
    key: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    data_type: str = Field(..., description="text, number, or select")
    options: Optional[List[PropertyOptionInput]] = None


class EventTypeCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    properties: Optional[List[PropertyDefinitionInput]] = None


class EventTypeUpdateRequest(BaseModel):
    name: Optional[str] = None
    properties: Optional[List[PropertyDefinitionInput]] = None


class SeriesCreateRequest(BaseModel):
    type_id: str
    interval_value: int = Field(..., gt=0)
    interval_unit: str = Field(..., description="day, week, or month")
    property_values: dict = Field(default_factory=dict)
    executed_on: str = Field(..., description="YYYY-MM-DD JST")
    note: Optional[str] = None
    media_id: Optional[str] = None
    count_contribution: Optional[int] = Field(None, ge=0)


class SeriesIntervalUpdateRequest(BaseModel):
    interval_value: int = Field(..., gt=0)
    interval_unit: str = Field(..., description="day, week, or month")


class RecordCreateRequest(BaseModel):
    executed_on: str = Field(..., description="YYYY-MM-DD JST")
    note: Optional[str] = None
    media_id: Optional[str] = None


class RecordUpdateRequest(BaseModel):
    executed_on: Optional[str] = None
    note: Optional[str] = None
    media_id: Optional[str] = None
    clear_media: bool = False
    count_contribution: Optional[int] = Field(None, ge=0)


# --- Event Type Endpoints ---

@router.get("/recurring-event-types")
def list_event_types(_=Depends(require_bearer_token)):
    """List all recurring event types."""
    return re_service.list_event_types()


@router.post("/recurring-event-types", status_code=status.HTTP_201_CREATED)
def create_event_type(req: EventTypeCreateRequest, _=Depends(require_bearer_token)):
    """Create a new recurring event type."""
    try:
        props = [p.model_dump() for p in req.properties] if req.properties is not None else None
        return re_service.create_event_type(name=req.name, properties=props)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/recurring-event-types/{type_id}")
def get_event_type(type_id: str, _=Depends(require_bearer_token)):
    """Get recurring event type detail."""
    try:
        return re_service.get_event_type(type_id)
    except re_service.EventTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/recurring-event-types/{type_id}")
def update_event_type(type_id: str, req: EventTypeUpdateRequest, _=Depends(require_bearer_token)):
    """Update recurring event type."""
    try:
        props = [p.model_dump() for p in req.properties] if req.properties is not None else None
        return re_service.update_event_type(type_id, name=req.name, properties=props)
    except re_service.EventTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except re_service.EventTypeSchemaLockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/recurring-event-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event_type(type_id: str, _=Depends(require_bearer_token)):
    """Delete recurring event type."""
    try:
        re_service.delete_event_type(type_id)
        return None
    except re_service.EventTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except re_service.EventTypeSchemaLockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# --- Series Endpoints ---

@router.get("/recurring-event-series")
def list_series(_=Depends(require_bearer_token)):
    """List all series sorted by next due date ASC."""
    return re_service.list_series()


@router.post("/recurring-event-series", status_code=status.HTTP_201_CREATED)
def create_series(req: SeriesCreateRequest, _=Depends(require_bearer_token)):
    """Create a new series along with its start record."""
    try:
        return re_service.create_series_with_start_record(
            type_id=req.type_id,
            interval_value=req.interval_value,
            interval_unit=req.interval_unit,
            property_values=req.property_values,
            executed_on=req.executed_on,
            note=req.note,
            media_id=req.media_id,
            count_contribution=req.count_contribution,
        )
    except re_service.EventTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except re_service.SeriesAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except re_service.InvalidExecutionDateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/recurring-event-series/{series_id}")
def get_series(series_id: str, _=Depends(require_bearer_token)):
    """Get series detail and execution record history."""
    try:
        return re_service.get_series_detail(series_id)
    except re_service.SeriesNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/recurring-event-series/{series_id}/interval")
def update_series_interval(
    series_id: str, req: SeriesIntervalUpdateRequest, _=Depends(require_bearer_token)
):
    """Update recommended interval of a series."""
    try:
        return re_service.update_series_interval(
            series_id=series_id,
            interval_value=req.interval_value,
            interval_unit=req.interval_unit,
        )
    except re_service.SeriesNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# --- Record Endpoints ---

@router.post("/recurring-event-series/{series_id}/records", status_code=status.HTTP_201_CREATED)
def add_execution_record(
    series_id: str, req: RecordCreateRequest, _=Depends(require_bearer_token)
):
    """Add a new execution record to a series."""
    try:
        return re_service.add_execution_record(
            series_id=series_id,
            executed_on=req.executed_on,
            note=req.note,
            media_id=req.media_id,
        )
    except re_service.SeriesNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except re_service.InvalidExecutionDateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/recurring-event-records/{record_id}")
def update_execution_record(
    record_id: str, req: RecordUpdateRequest, _=Depends(require_bearer_token)
):
    """Update an execution record."""
    try:
        return re_service.update_execution_record(
            record_id=record_id,
            executed_on=req.executed_on,
            note=req.note,
            media_id=req.media_id,
            clear_media=req.clear_media,
            count_contribution=req.count_contribution,
        )
    except re_service.RecordNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except re_service.InvalidExecutionDateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/recurring-event-records/{record_id}")
def delete_execution_record(record_id: str, _=Depends(require_bearer_token)):
    """Delete an execution record."""
    try:
        series_id, series_deleted = re_service.delete_execution_record(record_id)
        return {
            "success": True,
            "series_id": series_id,
            "series_deleted": series_deleted,
        }
    except re_service.RecordNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
