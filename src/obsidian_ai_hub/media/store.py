"""On-disk + DB persistence for generated media.

Operation-scenario contract (see ``docs/development-quality-playbook.md``):

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| 保存 | provider の生バイト列 + metadata | `media_id` (サーバー生成 UUID hex) | `output_dir/<date>/<timestamp>-<short>.<ext>` + `generated_media` 行 | serving route | 書込み後の DB insert 失敗はファイルを削除して例外 | アプリ外ファイル書込み |
| 参照 | クライアント指定の `media_id` | DB 行が正本 (パスではない) | なし | browser | 未知/containment 失敗は `FileNotFoundError`/`ValueError` | なし |

The file is written first and the row inserted after, so a row never points at
a missing file (a crash between the two leaves only an orphan file, which the
serving route cannot reach). Clients never supply a filesystem path.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.media.generation import (
    GeneratedImage,
    extension_for_format,
)
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


def _resolve_output_dir() -> Path:
    raw = getattr(config, "IMAGE_GENERATION_OUTPUT_DIR", None)
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        raise ValueError(
            "Image output directory is not configured (image_generation.output_dir)"
        )
    return Path(raw).expanduser().resolve(strict=False)


def _resolve_contained_path(root: Path, relative_path: str) -> Path:
    """Return the resolved target for *relative_path* under *root*.

    Rejects absolute paths, ``..`` components, NUL bytes, and any resolve
    result that escapes *root* (including symlink escapes). The root itself is
    refused. Raises ``ValueError``; nothing is written on failure.
    """
    if not isinstance(relative_path, str) or relative_path.strip() == "":
        raise ValueError("relative_path must be a non-empty string")
    if "\x00" in relative_path:
        raise ValueError("relative_path must not contain NUL bytes")
    p = Path(relative_path)
    if p.is_absolute():
        raise ValueError("Absolute paths are not allowed")
    if ".." in p.parts:
        raise ValueError("Path traversal components (..) are not allowed")
    try:
        resolved = (root / p).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Unable to resolve media path: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("Path is outside the media output directory") from None
    if resolved == root:
        raise ValueError("Path must point to a file, not the output directory root")
    return resolved


def _reference(row: dict[str, Any]) -> dict[str, Any]:
    media_id = row["media_id"]
    return {
        "media_type": row["media_type"],
        "media_id": media_id,
        "url": f"/api/v1/media/{media_id}",
        "download_url": f"/api/v1/media/{media_id}/download",
        "mime_type": row["mime_type"],
        "width": row.get("width"),
        "height": row.get("height"),
        "filename": row["filename"],
    }


def save_generated_image(
    image: GeneratedImage,
    *,
    prompt: str,
    model: str,
    provider: str = "openai",
    width: int | None = None,
    height: int | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Atomically write *image* under the configured dir and record its row."""
    if not isinstance(image.data, (bytes, bytearray)) or not image.data:
        raise ValueError("image data must be non-empty bytes")

    root = _resolve_output_dir()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Unable to prepare media output directory: {exc}") from exc
    root = root.resolve(strict=False)

    media_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    date_dir = now.strftime("%Y-%m-%d")
    filename = (
        f"{now.strftime('%Y%m%d-%H%M%S')}-{media_id[:8]}"
        f".{extension_for_format(image.output_format)}"
    )
    relative_path = f"{date_dir}/{filename}"

    target = _resolve_contained_path(root, relative_path)
    parent = target.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Unable to create media parent directory: {exc}") from exc
    # Re-resolve after mkdir so a swapped parent symlink cannot redirect us.
    target = _resolve_contained_path(root, relative_path)

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(target.parent),
            prefix=".oaihub-media-",
            suffix=".part",
            delete=False,
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(image.data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, target)
        tmp_path = None
    except OSError as exc:
        raise OSError(f"Failed to write generated media file: {exc}") from exc
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    row = {
        "media_id": media_id,
        "media_type": "image",
        "relative_path": relative_path,
        "filename": filename,
        "mime_type": image.mime_type,
        "width": width,
        "height": height,
        "byte_size": len(image.data),
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
        "session_id": session_id,
        "run_id": run_id,
        "task_id": task_id,
        "created_at": now.isoformat(),
    }
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO generated_media (
                media_id, media_type, relative_path, filename, mime_type,
                width, height, byte_size, provider, model, prompt,
                metadata_json, session_id, run_id, task_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["media_id"],
                row["media_type"],
                row["relative_path"],
                row["filename"],
                row["mime_type"],
                row["width"],
                row["height"],
                row["byte_size"],
                row["provider"],
                row["model"],
                row["prompt"],
                row["metadata_json"],
                row["session_id"],
                row["run_id"],
                row["task_id"],
                row["created_at"],
            ),
        )
        conn.commit()
    except Exception:
        # Node: a committed row must never reference a missing file, and an
        # uncommitted row must not leave a reachable orphan. Remove the file
        # written above and re-raise the DB failure.
        try:
            os.unlink(target)
        except OSError:
            logger.warning("Failed to remove media file after DB insert failure: %s", target)
        raise
    finally:
        if conn is not None:
            conn.close()

    return _reference(row)


def get_generated_media(media_id: str) -> dict[str, Any] | None:
    """Return the ``generated_media`` row for *media_id*, or ``None``."""
    if not isinstance(media_id, str) or not media_id.strip():
        return None
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "SELECT * FROM generated_media WHERE media_id = ?", (media_id.strip(),)
        )
        row = cur.fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def resolve_generated_media_path(media_id: str) -> tuple[Path, dict[str, Any]]:
    """Resolve *media_id* to its contained on-disk path and row.

    Raises ``FileNotFoundError`` for unknown ids or missing files and
    ``ValueError`` when the stored relative path escapes the output root.
    """
    row = get_generated_media(media_id)
    if row is None:
        raise FileNotFoundError("Media not found")
    root = _resolve_output_dir()
    # A tampered row must not become a read outside the configured dir; a
    # ValueError here propagates to the route, which reports 404.
    path = _resolve_contained_path(root, str(row["relative_path"]))
    if not path.is_file():
        raise FileNotFoundError("Media file not found")
    return path, row
