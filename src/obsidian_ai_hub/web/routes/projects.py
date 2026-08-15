from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_bearer_token

router = APIRouter()


@router.get("/projects", response_model=list[schemas.Project])
def list_projects(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    _=Depends(require_bearer_token),
):
    return service.list_projects(domain=domain, status=status)


@router.post("/projects", response_model=schemas.ProjectDetail)
def create_project(
    body: schemas.ProjectCreateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.create_project(body)
    except service.ProjectConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "project_name_conflict"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/projects/candidates", response_model=list[schemas.ProjectCandidate])
def list_project_candidates(
    status: Optional[str] = "unresolved",
    _=Depends(require_bearer_token),
):
    return service.list_project_candidates(status=status)


@router.get("/projects/candidates/{candidate_id}", response_model=schemas.ProjectCandidateDetail)
def get_project_candidate(candidate_id: int, _=Depends(require_bearer_token)):
    c = service.get_project_candidate_detail(candidate_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return c


@router.get("/projects/{project_id}", response_model=schemas.ProjectDetail)
def get_project(project_id: int, _=Depends(require_bearer_token)):
    p = service.get_project_detail(project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


@router.patch("/projects/{project_id}", response_model=schemas.ProjectDetail)
def update_project(
    project_id: int,
    body: schemas.ProjectUpdateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.update_project(project_id, body)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.ProjectConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "project_name_conflict"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects/candidates/{candidate_id}/resolve")
def resolve_project_candidate(
    candidate_id: int,
    body: schemas.ProjectCandidateResolveRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.resolve_project_candidate(candidate_id, body)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.ProjectConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "project_name_conflict"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
