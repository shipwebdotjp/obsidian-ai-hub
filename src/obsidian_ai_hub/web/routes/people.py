import logging

from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_bearer_token

logger = logging.getLogger(__name__)

# NOTE: Static route prefixes (/people/candidates, /people/duplicates,
# /people/vault-report, /people/merge, /people/sync) must be declared before the
# parametrized /people/{person_id} routes so that "candidates" etc. are not
# captured as a person_id.

router = APIRouter()


@router.get("/people", response_model=list[schemas.Person])
def get_people(_=Depends(require_bearer_token)):
    return service.list_people()


@router.get("/people/candidates", response_model=list[schemas.PersonCandidate])
def get_people_candidates(
    status: Literal["unresolved", "rejected"] = Query("unresolved"),
    _=Depends(require_bearer_token),
):
    return service.list_person_candidates(status=status)


@router.post(
    "/people/candidates/{candidate_id}/reject",
    response_model=schemas.PersonActionResponse,
)
def reject_person_candidate(candidate_id: str, _=Depends(require_bearer_token)):
    try:
        service.reject_person_candidate(candidate_id)
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post(
    "/people/candidates/{candidate_id}/reopen",
    response_model=schemas.PersonActionResponse,
)
def reopen_person_candidate(candidate_id: str, _=Depends(require_bearer_token)):
    try:
        service.reopen_person_candidate(candidate_id)
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/people/duplicates", response_model=schemas.DuplicatesResponse)
def get_people_duplicates(_=Depends(require_bearer_token)):
    return service.get_duplicate_candidates()


@router.get("/people/vault-report", response_model=schemas.SyncPeopleResponse)
def get_vault_report(_=Depends(require_bearer_token)):
    try:
        return service.get_vault_report_dynamic()
    except Exception:
        logger.exception("Failed to get vault report")
        raise HTTPException(status_code=500, detail="Failed to get vault report")


@router.get("/people/{person_id}", response_model=schemas.PersonDetail)
def get_person(person_id: str, _=Depends(require_bearer_token)):
    item = service.get_person_detail(person_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return item


@router.patch("/people/{person_id}", response_model=schemas.PersonDetail)
def update_person(
    person_id: str,
    body: schemas.PersonEditRequest,
    _=Depends(require_bearer_token),
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
    _=Depends(require_bearer_token),
):
    try:
        return service.delete_person(person_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/people/candidates/{candidate_id}", response_model=schemas.PersonCandidateDetail
)
def get_person_candidate(candidate_id: str, _=Depends(require_bearer_token)):
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
    _=Depends(require_bearer_token),
):
    try:
        service.assign_candidate_summary(
            candidate_id, summary_id, body.target_person_id
        )
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except service.CandidateRejectedError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "candidate_rejected"},
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/people/candidates/{candidate_id}/resolve",
    response_model=schemas.PersonActionResponse,
)
def resolve_person_candidate(
    candidate_id: str,
    body: schemas.CandidateResolveRequest,
    _=Depends(require_bearer_token),
):
    try:
        service.resolve_person_candidate(candidate_id, body.target_person_id)
        return {"success": True}
    except service.CandidateRejectedError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "candidate_rejected"},
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


@router.post("/people/candidates/{candidate_id}/promote", response_model=schemas.PersonDetail)
def promote_person_candidate(
    candidate_id: str,
    body: schemas.PersonPromoteRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.promote_person_candidate(candidate_id, body.display_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except service.CandidateRejectedError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "candidate_rejected"},
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


@router.post("/people/merge/preview", response_model=schemas.PeopleMergePreviewResponse)
def preview_people_merge(
    body: schemas.PeopleMergeRequest, _=Depends(require_bearer_token)
):
    return service.preview_people_merge(body.from_person_id, body.to_person_id)


@router.post("/people/merge", response_model=schemas.PersonActionResponse)
def merge_people(
    body: schemas.PeopleMergeRequest, _=Depends(require_bearer_token)
):
    try:
        service.merge_people(body.from_person_id, body.to_person_id)
        return {"success": True}
    except service.SelfRelationConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "self_relation"},
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/people/{person_id}/aliases", response_model=schemas.PersonDetail)
def delete_person_alias(
    person_id: str,
    normalized_name: str = Query(...),
    _=Depends(require_bearer_token),
):
    try:
        return service.delete_person_alias(person_id, normalized_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/people/sync", response_model=schemas.SyncPeopleResponse)
def sync_people(_=Depends(require_bearer_token)):
    try:
        return service.sync_people()
    except Exception:
        logger.exception("Failed to sync people")
        raise HTTPException(status_code=500, detail="Failed to sync people")


# --- Person Relation Types Routes ---


@router.get("/person-relation-types", response_model=list[schemas.PersonRelationType])
def list_person_relation_types(_=Depends(require_bearer_token)):
    return service.list_person_relation_types()


@router.post(
    "/person-relation-types",
    response_model=schemas.PersonRelationType,
    status_code=status.HTTP_201_CREATED,
)
def create_person_relation_type(
    body: schemas.PersonRelationTypeCreateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.create_person_relation_type(
            slug=body.slug,
            forward_label=body.forward_label,
            reverse_label=body.reverse_label,
            directionality=body.directionality,
            description=body.description,
        )
    except service.SlugConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "slug_conflict"},
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch(
    "/person-relation-types/{relation_type_id}",
    response_model=schemas.PersonRelationType,
)
def update_person_relation_type(
    relation_type_id: str,
    body: schemas.PersonRelationTypeUpdateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.update_person_relation_type(
            relation_type_id,
            forward_label=body.forward_label,
            reverse_label=body.reverse_label,
            description=body.description,
            is_active=body.is_active,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# --- Person Relations Routes ---


@router.get(
    "/people/{person_id}/relations",
    response_model=list[schemas.PersonRelation],
)
def list_person_relations_for_person(
    person_id: str,
    status: Optional[Literal["upcoming", "active", "ended", "undated"]] = Query(None),
    _=Depends(require_bearer_token),
):
    try:
        return service.list_person_relations_for_person(person_id, status_filter=status)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/people/{person_id}/relations",
    response_model=schemas.RelationDuplicateMergeResponse,
)
def create_person_relation(
    person_id: str,
    body: schemas.PersonRelationCreateRequest,
    response: Response,
    _=Depends(require_bearer_token),
):
    try:
        rel, action = service.create_person_relation(
            person_id=person_id,
            subject_person_id=body.subject_person_id,
            object_person_id=body.object_person_id,
            relation_type_id=body.relation_type_id,
            started_on=body.started_on,
            ended_on=body.ended_on,
            note=body.note,
            initial_evidence=[ev.model_dump() for ev in body.initial_evidence],
        )
        if action == "created":
            response.status_code = status.HTTP_201_CREATED
        else:
            response.status_code = status.HTTP_200_OK
        return {"action": action, "relation": rel}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except service.SelfRelationError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "self_relation"},
        ) from e
    except service.InactiveRelationTypeError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "inactive_relation_type"},
        ) from e
    except (ValueError, service.InvalidDateError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch(
    "/person-relations/{relation_id}",
    response_model=schemas.RelationDuplicateMergeResponse,
)
def update_person_relation(
    relation_id: str,
    body: schemas.PersonRelationUpdateRequest,
    _=Depends(require_bearer_token),
):
    try:
        rel, action = service.update_person_relation(
            relation_id,
            started_on=body.started_on,
            ended_on=body.ended_on,
            note=body.note,
        )
        return {"action": action, "relation": rel}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (ValueError, service.InvalidDateError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete(
    "/person-relations/{relation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_person_relation(
    relation_id: str,
    _=Depends(require_bearer_token),
):
    try:
        service.delete_person_relation(relation_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# --- Person Relation Evidence Routes ---


@router.post(
    "/person-relations/{relation_id}/evidence",
    response_model=schemas.PersonRelation,
    status_code=status.HTTP_201_CREATED,
)
def add_relation_evidence(
    relation_id: str,
    body: schemas.PersonRelationEvidenceCreateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.add_relation_evidence(
            relation_id,
            source_type=body.source_type,
            source_ref=body.source_ref,
            quote=body.quote,
            note=body.note,
            observed_at=body.observed_at,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (ValueError, service.InvalidDateError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch(
    "/person-relation-evidence/{evidence_id}",
    response_model=schemas.PersonRelation,
)
def update_relation_evidence(
    evidence_id: str,
    body: schemas.PersonRelationEvidenceUpdateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.update_relation_evidence(
            evidence_id,
            source_ref=body.source_ref,
            quote=body.quote,
            note=body.note,
            observed_at=body.observed_at,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (ValueError, service.InvalidDateError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete(
    "/person-relation-evidence/{evidence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_relation_evidence(
    evidence_id: str,
    _=Depends(require_bearer_token),
):
    try:
        service.delete_relation_evidence(evidence_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
