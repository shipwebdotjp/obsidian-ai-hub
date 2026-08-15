import re
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import ValidationError

from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.summary.generation import SummaryGenerationError, generate_summary
from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_bearer_token

router = APIRouter()


@router.post(
    "/summary-dashboard/summaries/generate", response_model=schemas.SummaryDetail
)
def generate_dashboard_summary(
    body: dict[str, Any] = Body(...),
    _=Depends(require_bearer_token),
):
    try:
        request = schemas.SummaryGenerateRequest.model_validate(body)
        return generate_summary(
            request.period_type,
            target_date=request.target_date,
            target_month=request.target_month,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SummaryGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        # LLM parse/validation failures are upstream generation failures; request
        # shape errors were already rejected by the schema above.
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/summary-dashboard/home", response_model=schemas.DashboardHomeResponse)
def get_dashboard_home(_=Depends(require_bearer_token)):
    return service.get_dashboard_home()


@router.get("/summary-dashboard/browse", response_model=schemas.DashboardBrowseResponse)
def get_dashboard_browse(
    year: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    _=Depends(require_bearer_token),
):
    try:
        if year is not None:
            if not re.match(r"^\d{4}$", year):
                raise ValueError("Invalid year format")
        if month is not None:
            if not re.match(r"^\d{4}-\d{2}$", month):
                raise ValueError("Invalid month format")
            # Strict calendar parse by appending dummy day
            datetime.strptime(f"{month}-01", "%Y-%m-%d")
        return service.get_dashboard_browse(year=year, month=month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/summary-dashboard/edit-options", response_model=schemas.EditOptionsResponse
)
def get_edit_options(_=Depends(require_bearer_token)):
    return service.get_edit_options()


@router.get(
    "/summary-dashboard/summaries/{summary_id}", response_model=schemas.SummaryDetail
)
def get_dashboard_summary(summary_id: str, _=Depends(require_bearer_token)):
    res = summary_store.get_summary_by_id(summary_id)
    if res is None:
        raise HTTPException(status_code=404, detail="summary not found")
    return res


@router.patch(
    "/summary-dashboard/summaries/{summary_id}", response_model=schemas.SummaryDetail
)
def update_dashboard_summary(
    summary_id: str,
    body: schemas.SummaryUpdateRequest,
    _=Depends(require_bearer_token),
):
    try:
        result = service.update_summary_detail(summary_id, body)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="summary not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.delete(
    "/summary-dashboard/summaries/{summary_id}",
    response_model=schemas.SummaryDeleteResponse,
)
def delete_dashboard_summary(
    summary_id: str,
    _=Depends(require_bearer_token),
):
    success = service.delete_summary_detail(summary_id)
    if not success:
        raise HTTPException(status_code=404, detail="summary not found")
    return {"deleted": True, "summary_id": summary_id}


@router.get(
    "/summary-dashboard/days/{target_date}",
    response_model=schemas.DashboardDayDetailsResponse,
)
def get_dashboard_day_details(target_date: str, _=Depends(require_bearer_token)):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD"
        )
    try:
        # Strict calendar verification (raises ValueError for 2026-02-31 etc.)
        datetime.strptime(target_date, "%Y-%m-%d")
        return service.get_dashboard_day_details(target_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/summary-dashboard/stats", response_model=schemas.DashboardStatsResponse)
def get_dashboard_stats(
    start_date: str = Query(..., min_length=10, max_length=10),
    end_date: str = Query(..., min_length=10, max_length=10),
    _=Depends(require_bearer_token),
):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", start_date) or not re.match(
        r"^\d{4}-\d{2}-\d{2}$", end_date
    ):
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD"
        )
    try:
        return service.get_dashboard_stats(start_date, end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
