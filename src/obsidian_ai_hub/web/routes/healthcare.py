from fastapi import APIRouter, Depends, HTTPException, Query

from obsidian_ai_hub.web import schemas
from obsidian_ai_hub.web.routes.deps import require_bearer_token
from obsidian_ai_hub.web.services import healthcare as hc_service

router = APIRouter()


@router.get(
    "/healthcare/overview",
    response_model=schemas.HealthcareOverviewResponse,
)
def get_healthcare_overview(
    start_date: str = Query(..., min_length=10, max_length=10),
    end_date: str = Query(..., min_length=10, max_length=10),
    _=Depends(require_bearer_token),
):
    # Validation (format, ordering, range cap) is centralized in the service
    # layer where _validate_date_str uses datetime.strptime for strict
    # calendar validation. FastAPI enforces the 10-char length here.
    try:
        return hc_service.get_healthcare_overview(start_date, end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/healthcare/correlation",
    response_model=schemas.HealthcareCorrelationResponse,
)
def get_healthcare_correlation(
    metric_x: str = Query(..., min_length=1, description="Curated metric key for X axis"),
    metric_y: str = Query(..., min_length=1, description="Curated metric key for Y axis"),
    start_date: str = Query(..., min_length=10, max_length=10),
    end_date: str = Query(..., min_length=10, max_length=10),
    _=Depends(require_bearer_token),
):
    try:
        return hc_service.get_healthcare_correlation(metric_x, metric_y, start_date, end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
