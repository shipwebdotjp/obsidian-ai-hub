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
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

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


def media_reference(row: dict[str, Any]) -> dict[str, Any]:
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
    source: str = "generated",
    content_sha256: str | None = None,
    width: int | None = None,
    height: int | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    """Atomically write *image* under the configured dir and record its row.

    ``source`` is ``generated`` (provider output), ``upload`` (chat
    attachment) or ``import`` (path import). ``content_sha256`` enables
    deduplication when provided.
    """
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
        "source": source,
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
        "content_sha256": content_sha256,
        "session_id": session_id,
        "run_id": run_id,
        "task_id": task_id,
        "workflow_run_id": workflow_run_id,
        "created_at": now.isoformat(),
    }
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO generated_media (
                media_id, media_type, source, relative_path, filename,
                mime_type, width, height, byte_size, provider, model, prompt,
                metadata_json, content_sha256, session_id, run_id, task_id,
                workflow_run_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["media_id"],
                row["media_type"],
                row["source"],
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
                row["content_sha256"],
                row["session_id"],
                row["run_id"],
                row["task_id"],
                row["workflow_run_id"],
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

    return media_reference(row)


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


def find_media_by_sha256(content_sha256: str) -> dict[str, Any] | None:
    """Return the oldest row with *content_sha256*, or ``None``.

    Used to deduplicate re-ingested attachments/paths so the same bytes do not
    create a second file+row. Returns ``None`` for empty/unknown hashes.
    """
    if not isinstance(content_sha256, str) or not content_sha256.strip():
        return None
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "SELECT * FROM generated_media WHERE content_sha256 = ?"
            " ORDER BY created_at ASC LIMIT 1",
            (content_sha256.strip(),),
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


# --- Deletion ---
#
# Operation-scenario contract (see docs/development-quality-playbook.md):
#
# | 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
# | --- | --- | --- | --- | --- | --- | --- |
# | 手動削除 | client の `media_id` | DB 行が正本 | 行 + ファイルを削除 | ギャラリー/UI | 未知 id は削除せず False | ファイル/行の削除 |
# | 親連動削除 | 親 ID (`session_id`/`task_id`/`workflow_run_id`) | 親 ID | source='generated' の行 + ファイルのみ削除 | 親の削除処理 | ファイル欠落・unlink 失敗はログして行削除は継続 (best-effort) | ファイル/行の削除 |
#
# 設計: 入力 (upload/import) は共有・再利用され得るため親連動では残す。ファイルを先に
# unlink し、その後に行を削除する（クラッシュ時は行が欠落ファイルを指し 404 になるだけで、
# 孤児ファイルより安全側）。親の削除はメディア処理の失敗で止めない。

def _unlink_media_file(root: Path, relative_path: str) -> None:
    """Best-effort delete of a media file; never raises."""
    try:
        path = _resolve_contained_path(root, relative_path)
    except ValueError as exc:
        logger.warning("Refusing to delete media outside output dir: %s", exc)
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("Failed to delete media file %s: %s", path, exc)


def delete_media(media_id: str) -> bool:
    """Delete one media row and its file. Returns ``False`` if unknown."""
    row = get_generated_media(media_id)
    if row is None:
        return False
    root = _resolve_output_dir()
    _unlink_media_file(root, str(row["relative_path"]))
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "DELETE FROM generated_media WHERE media_id = ?", (row["media_id"],)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def unlink_media_paths(relative_paths: "Sequence[str] | None") -> None:
    """Best-effort unlink of media files by output-root-relative path."""
    if not relative_paths:
        return
    try:
        root = _resolve_output_dir()
    except ValueError as exc:
        logger.warning("Cannot delete media files: %s", exc)
        return
    for relative_path in relative_paths:
        _unlink_media_file(root, str(relative_path))


_PARENT_COLUMNS = {
    "session": "session_id",
    "task": "task_id",
    "workflow": "workflow_run_id",
}
# Keep an IN(...) clause well under SQLite's bind-variable limit.
_MEDIA_DELETE_CHUNK = 400


def delete_generated_media_for_parents(
    kind: str,
    parent_ids: "Sequence[str]",
    *,
    conn: "sqlite3.Connection | None" = None,
) -> list[str]:
    """Delete generated output rows for several parents; return their paths.

    ``kind`` is ``session`` / ``task`` / ``workflow``. Only ``source =
    'generated'`` rows are removed: uploads/imports may be shared across
    parents and are left to manual deletion.

    When ``conn`` is omitted the rows are committed and the files unlinked
    here. When ``conn`` is supplied the rows are deleted in the caller's
    transaction and the returned paths must be unlinked by the caller *after*
    that transaction commits (via :func:`unlink_media_paths`), so a rollback
    never leaves live rows pointing at deleted files.
    """
    column = _PARENT_COLUMNS.get(kind)
    if column is None:
        raise ValueError(f"Unknown media parent kind: {kind!r}")
    ids = [str(pid) for pid in parent_ids if pid]
    if not ids:
        return []

    own_conn = conn is None
    active = conn if conn is not None else get_db_connection()
    removed_paths: list[str] = []
    try:
        # Chunk ids so the IN clause stays under SQLite's bind-variable limit
        # even for a large purge / workflow deletion.
        for start in range(0, len(ids), _MEDIA_DELETE_CHUNK):
            chunk = ids[start : start + _MEDIA_DELETE_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            rows = active.execute(
                f"SELECT media_id, relative_path FROM generated_media"
                f" WHERE source = 'generated' AND {column} IN ({placeholders})",
                chunk,
            ).fetchall()
            if not rows:
                continue
            removed_paths.extend(str(row["relative_path"]) for row in rows)
            active.executemany(
                "DELETE FROM generated_media WHERE media_id = ?",
                [(row["media_id"],) for row in rows],
            )
        if not removed_paths:
            return []
        if own_conn:
            active.commit()
            unlink_media_paths(removed_paths)
        return removed_paths
    finally:
        if own_conn:
            active.close()


def delete_generated_media_for_parent(
    kind: str,
    parent_id: str,
    *,
    conn: "sqlite3.Connection | None" = None,
) -> list[str]:
    """Delete one parent's generated output rows; return their relative paths."""
    if not isinstance(parent_id, str) or not parent_id:
        return []
    return delete_generated_media_for_parents(kind, [parent_id], conn=conn)
