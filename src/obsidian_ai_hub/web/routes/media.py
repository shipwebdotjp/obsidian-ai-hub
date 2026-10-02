"""Authenticated serving of generated media artifacts.

The browser cannot put the Bearer token on an ``<img src>`` request, so the
frontend fetches these endpoints and renders an object URL. ``media_id`` is
the only client-supplied identifier; the filesystem path and containment check
come from the ``generated_media`` row plus the configured output root.
"""

import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from obsidian_ai_hub.media import store
from obsidian_ai_hub.web.routes.deps import require_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter()

_UNSAFE_FILENAME_RE = re.compile(r'[\r\n"\\\x00-\x1f]')


def _safe_filename(row: dict, fallback: str) -> str:
    name = str(row.get("filename") or fallback)
    name = _UNSAFE_FILENAME_RE.sub("_", name).strip()
    return name or fallback


def _media_response(media_id: str, *, download: bool) -> FileResponse:
    try:
        path, row = store.resolve_generated_media_path(media_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        # A tampered relative_path must not reveal an outside file; report 404.
        logger.warning("generated media containment failure for %s: %s", media_id, exc)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Media not found"
        ) from exc

    disposition = "attachment" if download else "inline"
    filename = _safe_filename(row, path.name)
    return FileResponse(
        path,
        media_type=str(row.get("mime_type") or "application/octet-stream"),
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.post("/media/upload", status_code=status.HTTP_201_CREATED)
async def upload_media(file: UploadFile = File(...), _=Depends(require_bearer_token)):
    """Upload an image file to the media library."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image files are supported",
        )
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty"
        )

    sub_type = file.content_type.split("/")[-1].lower()
    if sub_type in ("jpeg", "jpg"):
        fmt = "jpg"
    elif sub_type in ("png", "webp", "gif"):
        fmt = sub_type
    else:
        fmt = "png"

    from obsidian_ai_hub.media.generation import GeneratedImage

    image = GeneratedImage(
        data=content,
        mime_type=file.content_type,
        output_format=fmt,
    )
    return store.save_generated_image(
        image,
        prompt=file.filename or "uploaded image",
        model="upload",
        provider="user",
        source="upload",
    )


@router.get("/media")
def list_media(
    media_type: Optional[str] = Query(None, description="Filter by media_type (e.g. image)"),
    source: Optional[str] = Query(None, description="Filter by source (generated, upload, import)"),
    session_id: Optional[str] = Query(None, description="Filter by session_id"),
    task_id: Optional[str] = Query(None, description="Filter by task_id"),
    workflow_run_id: Optional[str] = Query(None, description="Filter by workflow_run_id"),
    q: Optional[str] = Query(None, description="Keyword search in prompt, filename, model"),
    limit: int = Query(50, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Keyset pagination cursor"),
    _=Depends(require_bearer_token),
):
    """List generated media items with pagination and filtering."""
    return store.list_generated_media(
        media_type=media_type,
        source=source,
        session_id=session_id,
        task_id=task_id,
        workflow_run_id=workflow_run_id,
        q=q,
        limit=limit,
        cursor=cursor,
    )


@router.get("/media/{media_id}/info")
def get_media_info(media_id: str, _=Depends(require_bearer_token)):
    """Get metadata detail for a specific media_id."""
    row = store.get_generated_media(media_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Media not found"
        )
    meta = {}
    if row.get("metadata_json"):
        try:
            meta = json.loads(row["metadata_json"])
        except Exception:
            meta = {}
    res = dict(row)
    res["metadata"] = meta
    res["url"] = f"/api/v1/media/{media_id}"
    res["download_url"] = f"/api/v1/media/{media_id}/download"
    return res


@router.get("/media/{media_id}")
def get_media(media_id: str, _=Depends(require_bearer_token)):
    return _media_response(media_id, download=False)


@router.get("/media/{media_id}/download")
def download_media(media_id: str, _=Depends(require_bearer_token)):
    return _media_response(media_id, download=True)


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(media_id: str, _=Depends(require_bearer_token)):
    """Delete one media row and its file (manual, irreversible)."""
    try:
        if not store.delete_media(media_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Media not found"
            )
    except store.MediaReferencedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return None
