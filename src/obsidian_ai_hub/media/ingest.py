"""Ingest input images (chat attachments / file paths) into ``generated_media``.

Editing needs the raw input bytes, but tool arguments must stay small and
client-supplied filesystem paths are a risk. This module is the single
boundary that turns an attachment or a path into a stable ``media_id``, so
``image_edit`` always references the media library.

Operation-scenario contract (see ``docs/development-quality-playbook.md``):

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| 検証 | 添付(base64) / `source_path` | 内容 SHA-256 | なし | 本サービス | 形式・寸法・サイズ不正、許可ルート外は例外 | なし |
| 取込 | 検証済みバイト列 | サーバー生成 `media_id` | 出力ディレクトリ + `generated_media` 行 (source=upload/import) | image_edit / ギャラリー | 同一 SHA-256 が既存なら再書込みしない (単一ライタ前提の best-effort) | アプリ外ファイル書込み |

Relative ``source_path`` resolves under ``IMAGE_GENERATION_INPUT_DIR``
(defaults to the Vault); absolute paths must resolve inside an allowed root
(Vault / output dir / input dir). No client path escapes those roots.
"""

from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path
from typing import Any, Sequence

from obsidian_ai_hub.media import store as media_store
from obsidian_ai_hub.media.generation import (
    GeneratedImage,
    mime_for_format,
)
from obsidian_ai_hub.utils import config

_ALLOWED_FORMATS = {"PNG": "png", "JPEG": "jpeg", "WEBP": "webp"}
_MAX_INPUT_PIXELS = 40_000_000


def _configured_roots() -> list[Path]:
    roots: list[Path] = []
    for raw in (
        getattr(config, "VAULT_PATH", None),
        getattr(config, "IMAGE_GENERATION_OUTPUT_DIR", None),
        getattr(config, "IMAGE_GENERATION_INPUT_DIR", None),
    ):
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            continue
        resolved = Path(raw).expanduser().resolve(strict=False)
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _resolve_input_path(source_path: str) -> Path:
    """Validate *source_path* and return a resolved file inside an allowed root."""
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValueError("source_path must be a non-empty string")
    if "\x00" in source_path:
        raise ValueError("source_path must not contain NUL bytes")
    p = Path(source_path)
    if ".." in p.parts:
        raise ValueError("Path traversal components (..) are not allowed")
    if p.is_absolute():
        candidate = p
    else:
        input_dir = getattr(config, "IMAGE_GENERATION_INPUT_DIR", None)
        if input_dir is None:
            raise ValueError("Input directory is not configured")
        candidate = Path(input_dir).expanduser() / p
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError("Input image not found") from None
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Unable to resolve input image path: {exc}") from exc

    roots = _configured_roots()
    if not any(resolved.is_relative_to(root) for root in roots):
        raise ValueError(
            "Input image path is outside the allowed roots"
            " (Vault, media output dir, or input dir)"
        )
    if not resolved.is_file():
        raise FileNotFoundError("Input image is not a file")
    return resolved


def _decode_and_validate(data: bytes) -> tuple[str, int, int, str]:
    """Return ``(output_format, width, height, mime_type)`` for *data*."""
    if not data:
        raise ValueError("Input image is empty")
    max_bytes = int(
        getattr(config, "IMAGE_GENERATION_MAX_INPUT_BYTES", 8 * 1024 * 1024)
        or 8 * 1024 * 1024
    )
    if len(data) > max_bytes:
        raise ValueError(f"Input image exceeds the size limit ({max_bytes} bytes)")

    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a dependency
        raise RuntimeError("Pillow is required to validate input images")
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            width, height = img.size
            img.verify()
    except Image.DecompressionBombError as exc:
        raise ValueError("Input image is too large to process") from exc
    except (OSError, ValueError) as exc:
        raise ValueError(f"Input image is not a readable image: {exc}") from exc

    output_format = _ALLOWED_FORMATS.get(fmt)
    if output_format is None:
        raise ValueError(
            "Unsupported input image format; use PNG, JPEG, or WebP"
        )
    if width <= 0 or height <= 0:
        raise ValueError("Input image has invalid dimensions")
    if width * height > _MAX_INPUT_PIXELS:
        raise ValueError("Input image dimensions are too large")
    return output_format, width, height, mime_for_format(output_format)


def _ingest_bytes(
    data: bytes,
    *,
    source: str,
    prompt: str = "",
    session_id: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    output_format, width, height, mime_type = _decode_and_validate(data)
    content_sha256 = hashlib.sha256(data).hexdigest()

    # Best-effort dedup under the single-writer assumption: the check and the
    # insert use separate connections (and the sha index is non-unique), so two
    # truly concurrent ingests of identical bytes could each write a row. The
    # consequence is a duplicate row/file, not corruption; a UNIQUE index plus
    # conflict handling can tighten this if concurrency is ever added.
    existing = media_store.find_media_by_sha256(content_sha256)
    if existing is not None:
        return media_store.media_reference(existing)

    image = GeneratedImage(
        data=data, mime_type=mime_type, output_format=output_format
    )
    return media_store.save_generated_image(
        image,
        prompt=prompt,
        model="",
        # Ingested inputs are not provider output; leave provider empty so the
        # row is not mislabeled as OpenAI-generated.
        provider="",
        source=source,
        content_sha256=content_sha256,
        width=width,
        height=height,
        metadata={"source": source},
        session_id=session_id,
        run_id=run_id,
        task_id=task_id,
    )


def ingest_path(
    source_path: str,
    *,
    prompt: str = "",
    session_id: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Ingest a file path (Task/Workflow input) and return its media reference."""
    resolved = _resolve_input_path(source_path)
    max_bytes = int(
        getattr(config, "IMAGE_GENERATION_MAX_INPUT_BYTES", 8 * 1024 * 1024)
        or 8 * 1024 * 1024
    )
    try:
        with open(resolved, "rb") as fh:
            data = fh.read(max_bytes + 1)
    except OSError as exc:
        raise OSError(f"Unable to read input image: {exc}") from exc
    return _ingest_bytes(
        data,
        source="import",
        prompt=prompt,
        session_id=session_id,
        run_id=run_id,
        task_id=task_id,
    )


def ingest_attachment(
    attachments: Sequence[dict[str, Any]] | None,
    *,
    prompt: str = "",
    session_id: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any] | None:
    """Ingest the first image attachment and return its reference, or ``None``."""
    if not attachments:
        return None
    for item in attachments:
        if not isinstance(item, dict):
            continue
        mime = str(item.get("mime_type") or "")
        data_b64 = item.get("data")
        if not mime.startswith("image/") or not isinstance(data_b64, str):
            continue
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid attachment encoding: {exc}") from exc
        return _ingest_bytes(
            data,
            source="upload",
            prompt=prompt,
            session_id=session_id,
            run_id=run_id,
            task_id=task_id,
        )
    return None


def ingest_media_id(media_id: str) -> dict[str, Any]:
    """Return an existing media reference, verifying the row exists."""
    row = media_store.get_generated_media(media_id)
    if row is None:
        raise FileNotFoundError("Source media not found")
    if str(row.get("media_type")) != "image":
        raise ValueError("Source media is not an image")
    return media_store.media_reference(row)


def read_media_bytes(media_id: str) -> tuple[bytes, str]:
    """Return ``(bytes, mime_type)`` for an existing image media row."""
    row = media_store.get_generated_media(media_id)
    if row is None:
        raise FileNotFoundError("Source media not found")
    if str(row.get("media_type")) != "image":
        raise ValueError("Source media is not an image")
    path, resolved_row = media_store.resolve_generated_media_path(media_id)
    max_bytes = int(
        getattr(config, "IMAGE_GENERATION_MAX_INPUT_BYTES", 8 * 1024 * 1024)
        or 8 * 1024 * 1024
    )
    try:
        with open(path, "rb") as fh:
            data = fh.read(max_bytes + 1)
    except OSError as exc:
        raise OSError(f"Unable to read source media: {exc}") from exc
    if len(data) > max_bytes:
        raise ValueError("Source image exceeds the size limit")
    return data, str(resolved_row.get("mime_type") or "image/png")
