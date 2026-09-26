"""Image generation via the OpenAI Images API.

This module is the only boundary that talks to the image provider. The OpenAI
client factory is injectable so tests can supply a fake and stay offline; the
Registry tool validates its inputs against ``ImageGenerateInput`` before
calling here, and :mod:`obsidian_ai_hub.media.store` owns the filesystem/DB
writes.

The provider response may carry either ``b64_json`` (gpt-image style) or a
``url`` (DALL-E style); both are normalized to raw bytes here.
"""

from __future__ import annotations

import base64
import io
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from obsidian_ai_hub.utils import config

_EXTENSION_BY_FORMAT = {"png": "png", "jpeg": "jpg", "webp": "webp"}
_MIME_BY_FORMAT = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}

_ALLOWED_FETCH_SCHEMES = ("http", "https")
_MAX_PROVIDER_IMAGE_BYTES = 64 * 1024 * 1024


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse HTTP redirects so the scheme allowlist also covers redirects.

    Without this, a provider-supplied ``http(s)`` URL that redirects to a
    link-local/metadata or plain-HTTP host would bypass the check (SSRF).
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_URL_OPENER = urllib.request.build_opener(_NoRedirectHandler)


@dataclass(frozen=True)
class GeneratedImage:
    """One provider-produced image, normalized to raw bytes."""

    data: bytes
    mime_type: str
    output_format: str
    revised_prompt: str | None = None


def extension_for_format(output_format: str) -> str:
    return _EXTENSION_BY_FORMAT.get(output_format, "png")


def mime_for_format(output_format: str) -> str:
    return _MIME_BY_FORMAT.get(output_format, "image/png")


def _default_client_factory() -> Any:
    api_key = config.OPENAI_API_KEY
    if not api_key:
        raise RuntimeError("Environment variable OPENAI_API_KEY is not set")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency is installed
        raise RuntimeError(
            "openai is required for image generation. Install with: pip install -U openai"
        ) from exc
    return OpenAI(
        api_key=api_key, timeout=config.IMAGE_GENERATION_TIMEOUT_SECONDS
    )


def _field(item: Any, name: str) -> Any:
    """Read a response field from either a dict-like or object-like item."""
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _decode_item(item: Any) -> bytes:
    b64 = _field(item, "b64_json")
    if b64:
        try:
            data = base64.b64decode(b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Provider returned invalid base64 image data: {exc}") from exc
        if not data:
            raise ValueError("Provider returned an empty image payload")
        return data
    url = _field(item, "url")
    if url:
        scheme = urllib.parse.urlparse(str(url)).scheme.lower()
        if scheme not in _ALLOWED_FETCH_SCHEMES:
            raise ValueError(
                f"Provider image URL uses an unsupported scheme: {scheme or '(none)'}"
            )
        with _URL_OPENER.open(str(url), timeout=60) as resp:  # noqa: S310
            data = resp.read(_MAX_PROVIDER_IMAGE_BYTES + 1)
        if len(data) > _MAX_PROVIDER_IMAGE_BYTES:
            raise ValueError("Provider image payload exceeds the size limit")
        if not data:
            raise ValueError("Provider image URL returned an empty payload")
        return data
    raise ValueError("Provider response item has neither b64_json nor url")


def generate_images(
    prompt: str,
    *,
    model: str | None = None,
    size: str | None = None,
    quality: str | None = None,
    output_format: str | None = None,
    background: str | None = None,
    count: int = 1,
    client_factory: Callable[[], Any] | None = None,
) -> list[GeneratedImage]:
    """Generate ``count`` images for *prompt* and return them as bytes.

    ``config.ensure_external_allowed`` is enforced only for the real provider;
    an injected ``client_factory`` (tests) is treated as offline.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    if count < 1:
        raise ValueError("count must be at least 1")

    if client_factory is None:
        config.ensure_external_allowed("image generation")
        client = _default_client_factory()
    else:
        client = client_factory()

    effective_model = model or config.IMAGE_GENERATION_MODEL
    effective_size = size or config.IMAGE_GENERATION_DEFAULT_SIZE
    effective_quality = quality or config.IMAGE_GENERATION_DEFAULT_QUALITY
    effective_format = output_format or "png"

    kwargs: dict[str, Any] = {
        "model": effective_model,
        "prompt": prompt.strip(),
        "n": count,
        "size": effective_size,
        "quality": effective_quality,
        "output_format": effective_format,
    }
    if background:
        kwargs["background"] = background

    response = client.images.generate(**kwargs)
    raw_items = _field(response, "data") or []
    if not raw_items:
        raise ValueError("Provider returned no image data")

    results: list[GeneratedImage] = []
    for item in raw_items[:count]:
        results.append(
            GeneratedImage(
                data=_decode_item(item),
                mime_type=mime_for_format(effective_format),
                output_format=effective_format,
                revised_prompt=_field(item, "revised_prompt"),
            )
        )
    return results


def image_dimensions(data: bytes) -> tuple[int | None, int | None]:
    """Best-effort ``(width, height)`` for *data*; never raises."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a dependency
        return None, None
    try:
        with Image.open(io.BytesIO(data)) as img:
            return int(img.width), int(img.height)
    except Exception:  # noqa: BLE001 - dimensions are metadata, not correctness
        return None, None
