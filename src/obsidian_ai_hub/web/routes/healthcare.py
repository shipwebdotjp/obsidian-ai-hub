from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from obsidian_ai_hub.healthcare.export_zip import ExportZipError
from obsidian_ai_hub.web import schemas
from obsidian_ai_hub.web.routes.deps import require_bearer_token
from obsidian_ai_hub.web.services import healthcare as hc_service
from obsidian_ai_hub.web.services import healthcare_import as hc_import

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


@router.post(
    "/healthcare/import",
    response_model=schemas.HealthcareImportResponse,
)
def import_healthcare_archive(
    file: UploadFile | None = File(None, description="Apple Health export .zip"),
    path: str | None = Form(None, description="Server-side .zip path alternative"),
    _=Depends(require_bearer_token),
):
    """Differentially import an Apple Health export zip.

    Exactly one of ``file`` (browser upload) or ``path`` (server-side file) is
    required. Existing fingerprints are ignored, so re-importing a newer export
    only adds new rows.
    """
    normalized_path = path.strip() if path else ""
    if (file is None) == (normalized_path == ""):
        raise HTTPException(
            status_code=400,
            detail="file か path のどちらか一方を指定してください",
        )
    try:
        if file is not None:
            result = hc_import.import_from_upload(file)
        else:
            result = hc_import.import_from_path(normalized_path)
    except hc_import.ImportBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except hc_import.UploadTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except (FileNotFoundError, ExportZipError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    stats = schemas.HealthcareImportStats(
        **{name: result.get(name, 0) for name in schemas.HealthcareImportStats.model_fields}
    )
    return schemas.HealthcareImportResponse(
        import_id=result["import_id"],
        status="succeeded",
        source=result.get("source", normalized_path),
        stats=stats,
    )
