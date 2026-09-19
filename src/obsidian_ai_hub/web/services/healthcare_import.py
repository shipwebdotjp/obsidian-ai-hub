"""Healthcare import orchestration for the web API.

The import is synchronous by design: the route is a plain ``def`` so FastAPI
runs it in its threadpool and the event loop is not blocked. A process-local
lock serializes imports so two archives cannot interleave writes into the same
SQLite file. Failures propagate; the importer already rolls back partial rows
and records a ``failed`` import row before re-raising.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
from pathlib import Path

from fastapi import UploadFile

from obsidian_ai_hub.healthcare.importer import import_export_zip
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

# Hard cap on the uploaded archive. Extraction has its own (uncompressed) caps
# in healthcare.export_zip.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB
_CHUNK_BYTES = 1024 * 1024

_import_lock = threading.Lock()


class ImportBusyError(RuntimeError):
    """Raised when another healthcare import is already running."""


class UploadTooLargeError(RuntimeError):
    """Raised when an uploaded archive exceeds the size cap."""


def _staging_root() -> Path:
    root = Path(config.HEALTHCARE_IMPORT_STAGING_DIR).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _save_upload(upload: UploadFile, dest: Path) -> None:
    # Fail fast using the declared size before streaming gigabytes to disk.
    declared_size = getattr(upload, "size", None)
    if declared_size is not None and declared_size > MAX_UPLOAD_BYTES:
        raise UploadTooLargeError("アップロードされた zip がサイズ上限を超えています")
    written = 0
    with open(dest, "wb") as out:
        while True:
            chunk = upload.file.read(_CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                raise UploadTooLargeError("アップロードされた zip がサイズ上限を超えています")
            out.write(chunk)


def _run_import(zip_path: Path, *, source_label: str | None = None) -> dict:
    if not _import_lock.acquire(blocking=False):
        raise ImportBusyError("別のヘルスケア取込が実行中です。完了後に再試行してください")
    try:
        return import_export_zip(
            zip_path, staging_dir=_staging_root(), source_label=source_label
        )
    finally:
        _import_lock.release()


def import_from_upload(upload: UploadFile) -> dict:
    """Persist an uploaded archive to staging and import it differentially."""
    upload_dir = Path(tempfile.mkdtemp(prefix="healthcare_upload_", dir=_staging_root()))
    try:
        zip_path = upload_dir / "upload.zip"
        _save_upload(upload, zip_path)
        label = f"upload:{Path(upload.filename or 'export.zip').name}"
        return _run_import(zip_path, source_label=label)
    finally:
        try:
            shutil.rmtree(upload_dir, ignore_errors=False)
        except OSError:
            logger.warning("Failed to cleanup healthcare upload dir %s", upload_dir, exc_info=True)


def import_from_path(path_str: str) -> dict:
    """Import a server-side ``.zip`` path (avoids uploading huge archives)."""
    path = Path(path_str).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"zip が見つかりません: {path}")
    if path.suffix.lower() != ".zip":
        raise ValueError("取り込めるのは .zip ファイルのみです")
    return _run_import(path)
