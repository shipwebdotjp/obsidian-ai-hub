"""Tests for POST /api/v1/media/upload: HEIC conversion and existing formats.

Operation scenario (irreversible file + row write): an uploaded HEIC/HEIF is
validated and converted to JPEG before anything is persisted; the original
HEIC is never stored. ``media_id`` is the only client-visible identifier and
the converted bytes are the source of truth for format checks. Broken or
unsupported inputs stop with 400 and leave no file or row behind.
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from obsidian_ai_hub.media import store
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.web.app import create_app


def _heic(color: str = "blue", size: tuple[int, int] = (16, 12)) -> bytes:
    import pillow_heif

    img = Image.new("RGB", size, color)
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW: exercises orientation normalization
    exif[0x0132] = "2026:10:06 10:00:00"
    heif = pillow_heif.from_pillow(img)
    buf = io.BytesIO()
    heif.save(buf, format="HEIF", exif=exif.tobytes())
    return buf.getvalue()


def _png(color: str = "green", size: tuple[int, int] = (6, 4)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(color: str = "red", size: tuple[int, int] = (6, 4)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def media_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    out = tmp_path / "media-out"
    inputs = tmp_path / "media-input"
    out.mkdir(parents=True, exist_ok=True)
    inputs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_config, "IMAGE_GENERATION_OUTPUT_DIR", out)
    monkeypatch.setattr(app_config, "IMAGE_GENERATION_INPUT_DIR", inputs)
    return out


@pytest.fixture
def api_client(api_token: str) -> TestClient:
    return TestClient(create_app(host="127.0.0.1", port=0, token=api_token))


def _media_count() -> int:
    return len(store.list_generated_media(limit=100)["items"])


def _stored_files(out_dir) -> list:
    return [p for p in out_dir.rglob("*") if p.is_file()]


def test_heic_upload_converts_to_jpeg(media_env, api_client, api_auth_headers):
    payload = _heic()
    assert payload[4:8] == b"ftyp"  # genuinely HEIC input, not a renamed JPEG

    res = api_client.post(
        "/api/v1/media/upload",
        files={"file": ("photo.heic", payload, "image/heic")},
        headers=api_auth_headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    media_id = body["media_id"]
    assert body["mime_type"] == "image/jpeg"
    assert body["filename"].endswith(".jpg")

    row = store.get_generated_media(media_id)
    assert row is not None
    assert row["mime_type"] == "image/jpeg"
    assert row["relative_path"].endswith(".jpg")

    # Authenticated fetch returns the converted JPEG, oriented correctly.
    res = api_client.get(f"/api/v1/media/{media_id}", headers=api_auth_headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    served = Image.open(io.BytesIO(res.content))
    served.load()
    assert served.size == (12, 16)  # EXIF orientation 6 applied to 16x12
    assert served.mode == "RGB"
    assert served.getexif().get(0x0132) == "2026:10:06 10:00:00"

    # The browser <img> path requires auth.
    res = api_client.get(f"/api/v1/media/{media_id}")
    assert res.status_code == 401


def test_broken_or_unsupported_upload_leaves_no_trace(
    media_env, api_client, api_auth_headers
):
    bad_inputs = [
        # Valid ftyp box prefix so the payload reaches the HEIC converter,
        # then fails decoding (covers convert_heic_to_jpeg failure).
        ("broken.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 128, "image/heic"),
        ("truncated.heic", _heic()[:64], "image/heic"),
        ("note.txt", b"just a text file, not an image", "text/plain"),
    ]
    rows_before = _media_count()
    files_before = _stored_files(media_env)
    for filename, data, content_type in bad_inputs:
        res = api_client.post(
            "/api/v1/media/upload",
            files={"file": (filename, data, content_type)},
            headers=api_auth_headers,
        )
        assert res.status_code == 400, (filename, res.text)
    assert _media_count() == rows_before
    assert _stored_files(media_env) == files_before

    res = api_client.post(
        "/api/v1/media/upload",
        files={"file": ("empty.heic", b"", "image/heic")},
        headers=api_auth_headers,
    )
    assert res.status_code == 400
    assert _media_count() == rows_before


def test_png_and_jpeg_upload_unchanged(media_env, api_client, api_auth_headers):
    for filename, data, mime in [
        ("a.png", _png(), "image/png"),
        ("b.jpg", _jpeg(), "image/jpeg"),
    ]:
        res = api_client.post(
            "/api/v1/media/upload",
            files={"file": (filename, data, mime)},
            headers=api_auth_headers,
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["mime_type"] == mime

        fetched = api_client.get(
            f"/api/v1/media/{body['media_id']}", headers=api_auth_headers
        )
        assert fetched.status_code == 200
        assert fetched.headers["content-type"] == mime
        assert fetched.content == data
