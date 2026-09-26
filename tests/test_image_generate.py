"""Tests for the ``image_generate`` capability and generated-media serving.

Operation scenario (external send + out-of-app file write): validated inputs
flow to one provider call, the bytes are atomically written under the
configured output directory, a ``generated_media`` row is recorded, and the
authenticated route serves the file by ``media_id`` only. Provider or DB
failures stop without leaving a reachable artifact; path traversal is refused.

The provider is faked so the scenario is deterministic and offline.
"""

import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from obsidian_ai_hub.agents import registry as agent_registry
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.media import generation, store
from obsidian_ai_hub.tasks import capability_schemas
from obsidian_ai_hub.tasks.capabilities import get_capability_definitions
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.workflow.capabilities import is_workflow_capability


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 3), "red").save(buf, format="PNG")
    return buf.getvalue()


PNG_BYTES = _png_bytes()


class _FakeImages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        payload = base64.b64encode(PNG_BYTES).decode("ascii")
        n = int(kwargs.get("n", 1))
        return SimpleNamespace(
            data=[
                SimpleNamespace(b64_json=payload, revised_prompt=None)
                for _ in range(n)
            ]
        )


class _FakeClient:
    def __init__(self) -> None:
        self.images = _FakeImages()


@pytest.fixture
def media_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    out = tmp_path / "media-out"
    monkeypatch.setattr(app_config, "IMAGE_GENERATION_OUTPUT_DIR", out)
    fake = _FakeClient()
    monkeypatch.setattr(generation, "_default_client_factory", lambda: fake)
    return SimpleNamespace(dir=out, fake=fake)


@pytest.fixture
def api_client(api_token: str) -> TestClient:
    return TestClient(create_app(host="127.0.0.1", port=0, token=api_token))


def _tool():
    return agent_registry.TOOL_DEFINITIONS["image_generate"]["get_tool"]()


def _media_count() -> int:
    conn = get_db_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM generated_media").fetchone()[0]
    finally:
        conn.close()


def test_tool_writes_file_and_row(media_env):
    res = json.loads(
        _tool().invoke({"prompt": "a red square", "count": 2})
    )
    assert "error" not in res
    assert res["model"] == app_config.IMAGE_GENERATION_MODEL
    assert len(res["images"]) == 2

    ref = res["images"][0]
    assert ref["media_id"]
    assert ref["mime_type"] == "image/png"
    assert ref["width"] == 4 and ref["height"] == 3
    assert ref["url"] == f"/api/v1/media/{ref['media_id']}"

    row = store.get_generated_media(ref["media_id"])
    assert row is not None
    path = media_env.dir / row["relative_path"]
    assert path.is_file()
    assert path.read_bytes() == PNG_BYTES
    assert _media_count() == 2


def test_llm_quality_locked_for_context(media_env):
    tool = agent_registry.TOOL_DEFINITIONS["image_generate"][
        "get_tool_with_context"
    ]({"llm_decides_params": True})
    tool.invoke({"prompt": "x", "quality": "high"})
    assert media_env.fake.images.calls[-1]["quality"] == (
        app_config.IMAGE_GENERATION_LLM_QUALITY
    )


def test_quality_override_allowed_without_llm_context(media_env):
    res = json.loads(
        agent_registry.TOOL_DEFINITIONS["image_generate"]["get_tool"]().invoke(
            {"prompt": "x", "quality": "high"}
        )
    )
    assert "error" not in res
    assert media_env.fake.images.calls[-1]["quality"] == "high"


def test_llm_quality_lock_can_be_disabled(media_env, monkeypatch):
    monkeypatch.setattr(app_config, "IMAGE_GENERATION_LOCK_LLM_QUALITY", False)
    tool = agent_registry.TOOL_DEFINITIONS["image_generate"][
        "get_tool_with_context"
    ]({"llm_decides_params": True})
    res = json.loads(tool.invoke({"prompt": "x", "quality": "high"}))
    assert "error" not in res
    assert media_env.fake.images.calls[-1]["quality"] == "high"


def test_provider_failure_leaves_no_artifact(monkeypatch, tmp_path: Path):
    out = tmp_path / "media-fail"
    monkeypatch.setattr(app_config, "IMAGE_GENERATION_OUTPUT_DIR", out)

    def boom():
        raise RuntimeError("provider down")

    monkeypatch.setattr(generation, "_default_client_factory", boom)
    res = json.loads(_tool().invoke({"prompt": "x"}))
    assert "error" in res
    assert list(tmp_path.rglob("*.png")) == []
    assert not out.exists()
    assert _media_count() == 0


def test_db_failure_removes_written_file(monkeypatch, media_env):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "get_db_connection", boom)
    image = generation.GeneratedImage(
        data=PNG_BYTES, mime_type="image/png", output_format="png"
    )
    with pytest.raises(RuntimeError, match="db down"):
        store.save_generated_image(image, prompt="x", model="m")
    assert list(media_env.dir.rglob("*.png")) == []


def test_store_rejects_path_traversal(media_env):
    root = media_env.dir.resolve()
    for bad in ("../evil.png", "/etc/passwd", "a/../../evil.png", ""):
        with pytest.raises(ValueError):
            store._resolve_contained_path(root, bad)


def test_serving_route_serves_by_id(media_env, api_client, api_auth_headers):
    ref = json.loads(_tool().invoke({"prompt": "served"}))["images"][0]
    media_id = ref["media_id"]

    assert api_client.get(f"/api/v1/media/{media_id}").status_code == 401

    res = api_client.get(f"/api/v1/media/{media_id}", headers=api_auth_headers)
    assert res.status_code == 200
    assert res.content == PNG_BYTES
    assert res.headers["content-type"].startswith("image/png")
    assert "inline" in res.headers["content-disposition"]

    download = api_client.get(
        f"/api/v1/media/{media_id}/download", headers=api_auth_headers
    )
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]

    missing = api_client.get(
        "/api/v1/media/does-not-exist", headers=api_auth_headers
    )
    assert missing.status_code == 404


def test_capability_derived_with_plan_required_policy():
    by_key = {d.key: d for d in get_capability_definitions()}
    definition = by_key["image_generate"]
    assert definition.adapter_kind == "registry_tool"
    assert definition.registry_tool_id == "image_generate"
    assert definition.default_approval_policy == "plan_required"
    assert definition.read_only is False
    assert is_workflow_capability("image_generate")

    model = capability_schemas.resolve_input_model("image_generate")
    assert model is agent_registry.ImageGenerateInput
    assert capability_schemas.capability_output_schema("image_generate") is not None
    with pytest.raises(ValueError, match="inputs invalid"):
        capability_schemas.validate_capability_inputs(
            "image_generate", {"prompt": "x", "unknown": 1}
        )


def test_task_adapter_executes_end_to_end(media_env):
    from obsidian_ai_hub.tasks import store as task_store
    from obsidian_ai_hub.tasks.adapters import get_default_executor

    task = task_store.create_task("make an image")
    plan = task_store.create_plan(
        task["task_id"],
        {
            "purpose": "image",
            "steps": [
                {
                    "capability_key": "image_generate",
                    "title": "generate",
                    "target": {},
                    "inputs": {"prompt": "a task image", "count": 1},
                    "side_effects": "external image generation",
                }
            ],
            "completion_criteria": "done",
        },
        {"image_generate": "plan_required"},
    )
    result = get_default_executor().execute_step(
        task, plan, 0, plan["plan"]["steps"][0]
    )
    summary = json.loads(result.summary)
    assert summary["images"][0]["media_id"]


def test_url_fetch_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="unsupported scheme"):
        generation._decode_item({"url": "file:///etc/passwd"})


def test_url_fetch_refuses_redirects():
    # The handler returns None so urllib raises instead of following a redirect.
    handler = generation._NoRedirectHandler()
    assert (
        handler.redirect_request(
            None, None, 302, "Found", {}, "http://169.254.169.254/"
        )
        is None
    )


def test_url_fetch_caps_payload_size(monkeypatch):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, n=-1):
            return b"x" * n if isinstance(n, int) and n > 0 else b"x"

    class _Opener:
        def open(self, url, timeout=None):
            return _Resp()

    monkeypatch.setattr(generation, "_MAX_PROVIDER_IMAGE_BYTES", 8)
    monkeypatch.setattr(generation, "_URL_OPENER", _Opener())
    with pytest.raises(ValueError, match="size limit"):
        generation._decode_item({"url": "https://example.com/x.png"})


def test_migration_creates_generated_media_table():
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name='generated_media'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()
