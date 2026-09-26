"""Authenticated serving of generated media artifacts.

The browser cannot put the Bearer token on an ``<img src>`` request, so the
frontend fetches these endpoints and renders an object URL. ``media_id`` is
the only client-supplied identifier; the filesystem path and containment check
come from the ``generated_media`` row plus the configured output root.
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
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


@router.get("/media/{media_id}")
def get_media(media_id: str, _=Depends(require_bearer_token)):
    return _media_response(media_id, download=False)


@router.get("/media/{media_id}/download")
def download_media(media_id: str, _=Depends(require_bearer_token)):
    return _media_response(media_id, download=True)


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(media_id: str, _=Depends(require_bearer_token)):
    """Delete one media row and its file (manual, irreversible)."""
    if not store.delete_media(media_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Media not found"
        )
    return None
