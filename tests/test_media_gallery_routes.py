"""Tests for media list and info API routes and store functions."""

import io
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from obsidian_ai_hub.media import generation, store
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.web.app import create_app


def _png(color: str = "blue", size: tuple[int, int] = (10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
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


def _save_media(prompt: str = "a cat", model: str = "gpt-image-2.5", source: str = "generated", **kwargs):
    image = generation.GeneratedImage(
        data=_png(), mime_type="image/png", output_format="png"
    )
    return store.save_generated_image(
        image, prompt=prompt, model=model, source=source, **kwargs
    )


def test_list_and_info_media_routes(media_env, api_client, api_auth_headers):
    # Save a couple of items
    m1 = _save_media(prompt="sunset landscape", source="generated", session_id="s1")
    m2 = _save_media(prompt="cyberpunk city", source="upload", task_id="t1")

    # 1. Unauthenticated request
    res = api_client.get("/api/v1/media")
    assert res.status_code == 401

    # 2. List all media
    res = api_client.get("/api/v1/media", headers=api_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "has_more" in data
    assert len(data["items"]) == 2

    # 3. Filter by source
    res = api_client.get("/api/v1/media?source=upload", headers=api_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["media_id"] == m2["media_id"]

    # 4. Keyword search q
    res = api_client.get("/api/v1/media?q=sunset", headers=api_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["media_id"] == m1["media_id"]

    # 5. Get media info
    res = api_client.get(f"/api/v1/media/{m1['media_id']}/info", headers=api_auth_headers)
    assert res.status_code == 200
    info = res.json()
    assert info["media_id"] == m1["media_id"]
    assert info["prompt"] == "sunset landscape"
    assert info["session_id"] == "s1"
    assert "url" in info
    assert "download_url" in info

    # 6. Nonexistent media info
    res = api_client.get("/api/v1/media/nonexistent_id/info", headers=api_auth_headers)
    assert res.status_code == 404


def test_list_media_pagination(media_env):
    items = []
    for i in range(5):
        items.append(_save_media(prompt=f"prompt {i}"))

    # Page limit 2
    res1 = store.list_generated_media(limit=2)
    assert len(res1["items"]) == 2
    assert res1["has_more"] is True
    assert res1["next_cursor"] is not None

    # Next page
    res2 = store.list_generated_media(limit=2, cursor=res1["next_cursor"])
    assert len(res2["items"]) == 2
    assert res2["has_more"] is True
    assert res2["items"][0]["media_id"] != res1["items"][0]["media_id"]

    # Third page
    res3 = store.list_generated_media(limit=2, cursor=res2["next_cursor"])
    assert len(res3["items"]) == 1
    assert res3["has_more"] is False
    assert res3["next_cursor"] is None
