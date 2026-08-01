import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_loopback_or_token

logger = logging.getLogger(__name__)

# NOTE: Static route prefixes (/people/candidates, /people/duplicates,
# /people/vault-report, /people/merge, /people/sync) must be declared before the
# parametrized /people/{person_id} routes so that "candidates" etc. are not
# captured as a person_id.

router = APIRouter()


@router.get("/people", response_model=list[schemas.Person])
def get_people(_=Depends(require_loopback_or_token)):
    return service.list_people()


@router.get("/people/candidates", response_model=list[schemas.PersonCandidate])
def get_people_candidates(_=Depends(require_loopback_or_token)):
    return service.list_person_candidates()


@router.get("/people/duplicates", response_model=schemas.DuplicatesResponse)
def get_people_duplicates(_=Depends(require_loopback_or_token)):
    return service.get_duplicate_candidates()


@router.get("/people/vault-report", response_model=schemas.SyncPeopleResponse)
def get_vault_report(_=Depends(require_loopback_or_token)):
    try:
        return service.get_vault_report_dynamic()
    except Exception:
        logger.exception("Failed to get vault report")
        raise HTTPException(status_code=500, detail="Failed to get vault report")


@router.get("/people/{person_id}", response_model=schemas.PersonDetail)
def get_person(person_id: str, _=Depends(require_loopback_or_token)):
    item = service.get_person_detail(person_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return item


@router.patch("/people/{person_id}", response_model=schemas.PersonDetail)
def update_person(
    person_id: str,
    body: schemas.PersonEditRequest,
    _=Depends(require_loopback_or_token),
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
    _=Depends(require_loopback_or_token),
):
    try:
        return service.delete_person(person_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/people/candidates/{candidate_id}", response_model=schemas.PersonCandidateDetail
)
def get_person_candidate(candidate_id: str, _=Depends(require_loopback_or_token)):
    item = service.get_person_candidate_detail(candidate_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return item


@router.post(
    "/people/candidates/{candidate_id}/summaries/{summary_id}/assign",
    response_model=schemas.PersonActionResponse,
)
def assign_candidate_summary(
    candidate_id: str,
    summary_id: str,
    body: schemas.PersonAssignmentRequest,
    _=Depends(require_loopback_or_token),
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


@router.post(
    "/people/candidates/{candidate_id}/resolve",
    response_model=schemas.PersonActionResponse,
)
def resolve_person_candidate(
    candidate_id: str,
    body: schemas.CandidateResolveRequest,
    _=Depends(require_loopback_or_token),
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


@router.post("/people/candidates/{candidate_id}/promote", response_model=schemas.PersonDetail)
def promote_person_candidate(
    candidate_id: str,
    body: schemas.PersonPromoteRequest,
    _=Depends(require_loopback_or_token),
):
    try:
        return service.promote_person_candidate(candidate_id, body.display_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
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
    body: schemas.PeopleMergeRequest, _=Depends(require_loopback_or_token)
):
    return service.preview_people_merge(body.from_person_id, body.to_person_id)


@router.post("/people/merge", response_model=schemas.PersonActionResponse)
def merge_people(
    body: schemas.PeopleMergeRequest, _=Depends(require_loopback_or_token)
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
    _=Depends(require_loopback_or_token),
):
    try:
        return service.delete_person_alias(person_id, normalized_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/people/sync", response_model=schemas.SyncPeopleResponse)
def sync_people(_=Depends(require_loopback_or_token)):
    try:
        return service.sync_people()
    except Exception:
        logger.exception("Failed to sync people")
        raise HTTPException(status_code=500, detail="Failed to sync people")
