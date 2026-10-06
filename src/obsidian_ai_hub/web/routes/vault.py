import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/vaults", response_model=schemas.VaultListResponse)
def list_vaults(
    _=Depends(require_bearer_token),
):
    try:
        return service.list_vaults()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/vault-search", response_model=schemas.VaultSearchResponse)
def vault_search(
    q: str = Query(..., min_length=1),
    k: int = Query(10, ge=1, le=50),
    mode: str = Query("hybrid"),
    vault: list[str] | None = Query(None),
    _=Depends(require_bearer_token),
):
    if mode not in schemas.ALLOWED_VAULT_SEARCH_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"mode must be one of {sorted(schemas.ALLOWED_VAULT_SEARCH_MODES)}",
        )
    try:
        return service.search_vault(q=q, k=k, mode=mode, vault_ids=vault)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        logger.warning("vault search error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vault-file", response_model=schemas.VaultFileResponse)
def get_vault_file(
    path: str = Query(..., min_length=1),
    vault: str | None = Query(None),
    _=Depends(require_bearer_token),
):
    try:
        return service.get_vault_file(path, vault_id=vault)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/vault-files", response_model=schemas.VaultFilesResponse)
def list_vault_files(
    vault: str | None = Query(None),
    _=Depends(require_bearer_token),
):
    try:
        return service.list_vault_files(vault_id=vault)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
