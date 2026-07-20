import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security.utils import get_authorization_scheme_param

from obsidian_ai_hub.web import schemas, service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


def _require_loopback_or_token(request: Request) -> None:
    """
    Enforce bearer-token authentication when the server is bound to a
    non-loopback interface. Localhost binds (127.0.0.1, ::1) are exempt.
    """
    from obsidian_ai_hub.web.app import (  # local import to avoid cycle
        LOOPBACK_HOSTS,
        TOKEN,
        TOKEN_REQUIRED,
    )

    client_host = request.client.host if request.client else None
    if client_host in LOOPBACK_HOSTS:
        return

    if not TOKEN_REQUIRED:
        return

    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    scheme, param = get_authorization_scheme_param(auth or "")
    if scheme.lower() != "bearer" or not param or not hmac.compare_digest(param, TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/memories", response_model=schemas.MemoryListResponse)
def list_memories(
    status_filter: Optional[str] = Query(None, alias="status"),
    kind: Optional[str] = None,
    topic: Optional[str] = None,
    q: Optional[str] = None,
    _=Depends(_require_loopback_or_token),
):
    if status_filter and status_filter not in schemas.ALLOWED_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(schemas.ALLOWED_STATUS)}",
        )
    items = service.list_memories(status=status_filter, kind=kind, topic=topic, q=q)
    return schemas.MemoryListResponse(items=items, total=len(items))


@router.get("/memories/{memory_id}", response_model=schemas.MemoryDetail)
def get_memory(memory_id: str, _=Depends(_require_loopback_or_token)):
    m = service.get_memory(memory_id)
    if m is None:
        raise HTTPException(status_code=404, detail="memory not found")
    events = service.get_events(memory_id)
    detail = dict(m)
    detail["events"] = events
    return detail


@router.post("/memories/{memory_id}/review", response_model=schemas.ReviewResponse)
def review_memory(
    memory_id: str, body: schemas.ReviewRequest, _=Depends(_require_loopback_or_token)
):
    try:
        result = service.review_memory(memory_id, body.action, body.new_content)
    except LookupError:
        raise HTTPException(status_code=404, detail="memory not found")
    except ValueError as e:
        logger.warning("review validation error for %s: %s", memory_id, e)
        raise HTTPException(status_code=400, detail="invalid review request")
    return {"memory": result}


@router.post("/memories/{memory_id}/edit", response_model=schemas.UpdateResponse)
def edit_memory(
    memory_id: str, body: schemas.EditRequest, _=Depends(_require_loopback_or_token)
):
    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="no editable fields provided")
    try:
        result = service.update_memory(memory_id, payload)
    except ValueError as e:
        logger.warning("edit validation error for %s: %s", memory_id, e)
        raise HTTPException(status_code=400, detail="invalid edit request")
    if not result.get("found"):
        raise HTTPException(status_code=404, detail="memory not found")
    return result


@router.post("/memories/batch-review", response_model=schemas.BatchReviewResponse)
def batch_review(
    body: schemas.BatchReviewRequest, _=Depends(_require_loopback_or_token)
):
    if not body.memory_ids:
        raise HTTPException(status_code=400, detail="memory_ids must not be empty")
    try:
        return service.batch_review(body.memory_ids, body.action)
    except ValueError as e:
        logger.warning("batch review validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/memories/{candidate_id}/resolve", response_model=schemas.ResolveResponse)
def resolve_memory(
    candidate_id: str,
    body: schemas.ResolveRequest,
    _=Depends(_require_loopback_or_token),
):
    try:
        cand, target = service.resolve_memory(
            candidate_id,
            body.action,
            body.target_memory_id,
            integrated_content=body.integrated_content,
            switch_date=body.switch_date,
        )
        return {"candidate": cand, "target": target}
    except ValueError as e:
        logger.warning("resolve validation error for %s: %s", candidate_id, e)
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/memories/{memory_id}", response_model=schemas.DeleteResponse)
def delete_memory(memory_id: str, _=Depends(_require_loopback_or_token)):
    result = service.delete_memory(memory_id)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail="memory not found")
    return result


@router.post("/memories/batch-delete", response_model=schemas.BatchDeleteResponse)
def batch_delete(
    body: schemas.BatchDeleteRequest, _=Depends(_require_loopback_or_token)
):
    return service.batch_delete(body.memory_ids)


@router.get("/memory-options", response_model=schemas.MemoryOptionsResponse)
def get_memory_options(_=Depends(_require_loopback_or_token)):
    return service.get_memory_options()


@router.post(
    "/copilot-profile/render", response_model=schemas.RenderCopilotProfileResponse
)
def render_copilot_profile(_=Depends(_require_loopback_or_token)):
    try:
        updated_files = service.render_copilot_profile()
        return {"updated_files": updated_files}
    except Exception as e:
        logger.exception("Failed to render copilot profile from API")
        raise HTTPException(
            status_code=500, detail=f"Failed to render copilot profile: {str(e)}"
        ) from e


# --- Research Theme routes ---


@router.get("/research-themes", response_model=schemas.ResearchThemeListResponse)
def list_research_themes(
    status: Optional[str] = Query(None),
    job_status: Optional[str] = Query(None, alias="job_status"),
    q: Optional[str] = None,
    _=Depends(_require_loopback_or_token),
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
def get_research_theme(theme_id: str, _=Depends(_require_loopback_or_token)):
    item = service.get_research_theme(theme_id)
    if item is None:
        raise HTTPException(status_code=404, detail="research theme not found")
    return item


@router.post(
    "/research-themes/{theme_id}/review",
    response_model=schemas.ResearchThemeActionResponse,
)
def review_research_theme(
    theme_id: str,
    body: schemas.ResearchReviewRequest,
    _=Depends(_require_loopback_or_token),
):
    try:
        result = service.review_research_theme(
            theme_id, body.action, reason=body.reason
        )
    except ValueError as e:
        logger.warning("review research theme validation error for %s: %s", theme_id, e)
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="research theme not found")
    return {"theme": result}


@router.post("/research-themes/{theme_id}/rerun", response_model=schemas.ResearchJob)
def rerun_research_theme(theme_id: str, _=Depends(_require_loopback_or_token)):
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
    _=Depends(_require_loopback_or_token),
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


# --- Vault Search routes ---


@router.get("/vault-search", response_model=schemas.VaultSearchResponse)
def vault_search(
    q: str = Query(..., min_length=1),
    k: int = Query(10, ge=1, le=50),
    mode: str = Query("hybrid"),
    _=Depends(_require_loopback_or_token),
):
    if mode not in schemas.ALLOWED_VAULT_SEARCH_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"mode must be one of {sorted(schemas.ALLOWED_VAULT_SEARCH_MODES)}",
        )
    try:
        return service.search_vault(q=q, k=k, mode=mode)
    except ValueError as e:
        logger.warning("vault search error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vault-file", response_model=schemas.VaultFileResponse)
def get_vault_file(
    path: str = Query(..., min_length=1),
    _=Depends(_require_loopback_or_token),
):
    try:
        return service.get_vault_file(path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# --- Summary Dashboard routes ---


@router.get("/summary-dashboard/home", response_model=schemas.DashboardHomeResponse)
def get_dashboard_home(_=Depends(_require_loopback_or_token)):
    return service.get_dashboard_home()


@router.get("/summary-dashboard/browse", response_model=schemas.DashboardBrowseResponse)
def get_dashboard_browse(
    year: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    _=Depends(_require_loopback_or_token),
):
    import re
    from datetime import datetime

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
def get_edit_options(_=Depends(_require_loopback_or_token)):
    return service.get_edit_options()


@router.get(
    "/summary-dashboard/summaries/{summary_id}", response_model=schemas.SummaryDetail
)
def get_dashboard_summary(summary_id: str, _=Depends(_require_loopback_or_token)):
    from obsidian_ai_hub.summary import store as summary_store

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
    _=Depends(_require_loopback_or_token),
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
    _=Depends(_require_loopback_or_token),
):
    success = service.delete_summary_detail(summary_id)
    if not success:
        raise HTTPException(status_code=404, detail="summary not found")
    return {"deleted": True, "summary_id": summary_id}


@router.get(
    "/summary-dashboard/days/{target_date}",
    response_model=schemas.DashboardDayDetailsResponse,
)
def get_dashboard_day_details(target_date: str, _=Depends(_require_loopback_or_token)):
    import re
    from datetime import datetime

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
    _=Depends(_require_loopback_or_token),
):
    import re

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


# --- People Management routes ---


@router.get("/people", response_model=list[schemas.Person])
def get_people(_=Depends(_require_loopback_or_token)):
    return service.list_people()


@router.get("/people/candidates", response_model=list[schemas.PersonCandidate])
def get_people_candidates(_=Depends(_require_loopback_or_token)):
    return service.list_person_candidates()


@router.get("/people/duplicates", response_model=schemas.DuplicatesResponse)
def get_people_duplicates(_=Depends(_require_loopback_or_token)):
    return service.get_duplicate_candidates()


@router.get("/people/vault-report", response_model=schemas.SyncPeopleResponse)
def get_vault_report(_=Depends(_require_loopback_or_token)):
    try:
        rep = service.get_vault_report_dynamic()
        return {
            "synced": False,
            "loader_report": rep["loader_report"],
            "db_conflicts": rep["db_conflicts"],
        }
    except Exception as e:
        logger.exception("Failed to get vault report")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/people/{person_id}", response_model=schemas.PersonDetail)
def get_person(person_id: str, _=Depends(_require_loopback_or_token)):
    item = service.get_person_detail(person_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return item


@router.patch("/people/{person_id}", response_model=schemas.PersonDetail)
def update_person(
    person_id: str,
    body: schemas.PersonEditRequest,
    _=Depends(_require_loopback_or_token),
):
    try:
        return service.update_unlinked_person(
            person_id, display_name=body.display_name, aliases=body.aliases
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except service.VaultLinkedPersonError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "vault_linked_person"},
        ) from e
    except service.AssignmentConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "assignment_conflict"},
        ) from e
    except service.AliasConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "conflict_type": "alias_conflict",
                "existing_person_id": e.existing_person_id,
                "existing_person_name": e.existing_person_name,
            },
        ) from e
    except service.MainNameConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "conflict_type": "main_name_conflict",
                "existing_person_id": e.existing_person_id,
                "existing_person_name": e.existing_person_name,
            },
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/people/{person_id}", response_model=schemas.PersonDeleteResponse)
def delete_person(
    person_id: str,
    _=Depends(_require_loopback_or_token),
):
    try:
        return service.delete_person(person_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/people/candidates/{candidate_id}", response_model=schemas.PersonCandidateDetail
)
def get_person_candidate(candidate_id: str, _=Depends(_require_loopback_or_token)):
    item = service.get_person_candidate_detail(candidate_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return item


@router.post("/people/candidates/{candidate_id}/summaries/{summary_id}/assign")
def assign_candidate_summary(
    candidate_id: str,
    summary_id: str,
    body: schemas.PersonAssignmentRequest,
    _=Depends(_require_loopback_or_token),
):
    try:
        service.assign_candidate_summary(
            candidate_id, summary_id, body.target_person_id
        )
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/people/candidates/{candidate_id}/resolve")
def resolve_person_candidate(
    candidate_id: str,
    body: schemas.CandidateResolveRequest,
    _=Depends(_require_loopback_or_token),
):
    try:
        service.resolve_person_candidate(candidate_id, body.target_person_id)
        return {"success": True}
    except service.AssignmentConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "assignment_conflict"},
        ) from e
    except service.AliasConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "conflict_type": "alias_conflict",
                "existing_person_id": e.existing_person_id,
                "existing_person_name": e.existing_person_name,
            },
        ) from e
    except service.MainNameConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "conflict_type": "main_name_conflict",
                "existing_person_id": e.existing_person_id,
                "existing_person_name": e.existing_person_name,
            },
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/people/merge/preview", response_model=schemas.PeopleMergePreviewResponse)
def preview_people_merge(
    body: schemas.PeopleMergeRequest, _=Depends(_require_loopback_or_token)
):
    return service.preview_people_merge(body.from_person_id, body.to_person_id)


@router.post("/people/merge")
def merge_people(
    body: schemas.PeopleMergeRequest, _=Depends(_require_loopback_or_token)
):
    try:
        service.merge_people(body.from_person_id, body.to_person_id)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/people/{person_id}/aliases", response_model=schemas.PersonDetail)
def delete_person_alias(
    person_id: str,
    normalized_name: str = Query(...),
    _=Depends(_require_loopback_or_token),
):
    try:
        return service.delete_person_alias(person_id, normalized_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/people/sync", response_model=schemas.SyncPeopleResponse)
def sync_people(_=Depends(_require_loopback_or_token)):
    try:
        return service.sync_people()
    except Exception as e:
        logger.exception("Failed to sync people")
        raise HTTPException(status_code=500, detail=str(e))
