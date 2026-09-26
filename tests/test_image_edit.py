"""Tests for the ``image_edit`` capability and input ingestion.

Operation scenario (external send + out-of-app file write + input path read):
validated source (attachment / path / media id) is ingested into
``generated_media``, then one provider edit call runs, the result is saved as a
new row, and the tool returns references. Invalid input or an out-of-root path
stops before any provider call; the fake provider keeps the test offline.
"""

import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from obsidian_ai_hub.agents import registry as agent_registry
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.media import generation, ingest, store
from obsidian_ai_hub.tasks import capability_schemas
from obsidian_ai_hub.tasks.capabilities import get_capability_definitions
from obsidian_ai_hub.utils import config as app_config


def _png(color: str, size: tuple[int, int] = (6, 4)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeImages:
    def __init__(self) -> None:
        self.generate_calls: list[dict] = []
        self.edit_calls: list[dict] = []

    def _response(self, n: int, color: str):
        payload = base64.b64encode(_png(color)).decode("ascii")
        return SimpleNamespace(
            data=[
                SimpleNamespace(b64_json=payload, revised_prompt=None)
                for _ in range(n)
            ]
        )

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return self._response(int(kwargs.get("n", 1)), "green")

    def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        return self._response(int(kwargs.get("n", 1)), "blue")


class _FakeClient:
    def __init__(self) -> None:
        self.images = _FakeImages()


@pytest.fixture
def media_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    out = tmp_path / "media-out"
    inputs = tmp_path / "media-input"
    inputs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_config, "IMAGE_GENERATION_OUTPUT_DIR", out)
    monkeypatch.setattr(app_config, "IMAGE_GENERATION_INPUT_DIR", inputs)
    fake = _FakeClient()
    monkeypatch.setattr(generation, "_default_client_factory", lambda: fake)
    return SimpleNamespace(dir=out, inputs=inputs, fake=fake)


def _edit_tool(ctx: dict | None = None):
    factory = agent_registry.TOOL_DEFINITIONS["image_edit"]["get_tool_with_context"]
    return factory(ctx or {})


def _media_count() -> int:
    conn = get_db_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM generated_media").fetchone()[0]
    finally:
        conn.close()


def test_edit_by_media_id(media_env):
    # Ingest a source image directly into the media library.
    ref = ingest._ingest_bytes(_png("red"), source="upload")
    res = json.loads(
        _edit_tool().invoke(
            {"prompt": "make it blue", "source_media_id": ref["media_id"]}
        )
    )
    assert "error" not in res
    assert len(res["images"]) == 1
    out_ref = res["images"][0]
    assert out_ref["mime_type"] == "image/png"

    row = store.get_generated_media(out_ref["media_id"])
    metadata = json.loads(row["metadata_json"])
    assert metadata["operation"] == "edit"
    assert metadata["source_media_id"] == ref["media_id"]
    assert len(media_env.fake.images.edit_calls) == 1
    # Source row remains (source='upload'), output is a new row (source='generated').
    assert _media_count() == 2


def test_edit_by_relative_path(media_env):
    (media_env.inputs / "pic.png").write_bytes(_png("red"))
    res = json.loads(
        _edit_tool().invoke(
            {"prompt": "brighten", "source_path": "pic.png"}
        )
    )
    assert "error" not in res
    # Imported source + generated output.
    assert _media_count() == 2
    assert len(media_env.fake.images.edit_calls) == 1
    call = media_env.fake.images.edit_calls[0]
    assert call["prompt"] == "brighten"
    assert call["image"][0] == "source.png"
    # Omitted size/quality fall back to the configured defaults.
    assert call["size"] == app_config.IMAGE_GENERATION_DEFAULT_SIZE
    assert call["quality"] == app_config.IMAGE_GENERATION_DEFAULT_QUALITY


def test_edit_rejects_path_outside_roots(media_env):
    before = len(media_env.fake.images.edit_calls)
    res = json.loads(
        _edit_tool().invoke(
            {"prompt": "x", "source_path": "/etc/passwd"}
        )
    )
    assert "error" in res
    assert len(media_env.fake.images.edit_calls) == before
    assert _media_count() == 0


def test_edit_rejects_dotdot_path(media_env):
    res = json.loads(
        _edit_tool().invoke({"prompt": "x", "source_path": "../secret.png"})
    )
    assert "error" in res
    assert _media_count() == 0


def test_edit_requires_exactly_one_source(media_env):
    with pytest.raises(Exception):
        _edit_tool().invoke({"prompt": "x"})
    ref = ingest._ingest_bytes(_png("red"), source="upload")
    with pytest.raises(Exception):
        _edit_tool().invoke(
            {
                "prompt": "x",
                "source_media_id": ref["media_id"],
                "source_path": "pic.png",
            }
        )


def test_edit_uses_current_attachment(monkeypatch, media_env):
    attachment = {"name": "a.png", "mime_type": "image/png", "data": base64.b64encode(_png("red")).decode()}
    from obsidian_ai_hub.agents import store as agent_store

    monkeypatch.setattr(
        agent_store,
        "get_message",
        lambda message_id: {"message_id": message_id, "attachments": [attachment]},
    )
    res = json.loads(
        _edit_tool({"user_message_id": "msg1"}).invoke(
            {"prompt": "enlarge", "use_current_attachment": True}
        )
    )
    assert "error" not in res
    assert len(media_env.fake.images.edit_calls) == 1
    # The attachment was ingested as an upload row.
    conn = get_db_connection()
    try:
        sources = conn.execute(
            "SELECT source FROM generated_media ORDER BY created_at ASC"
        ).fetchall()
    finally:
        conn.close()
    assert [r["source"] for r in sources] == ["upload", "generated"]


def test_edit_no_attachment_errors(monkeypatch, media_env):
    from obsidian_ai_hub.agents import store as agent_store

    monkeypatch.setattr(agent_store, "get_message", lambda message_id: None)
    res = json.loads(
        _edit_tool({"user_message_id": "msg1"}).invoke(
            {"prompt": "x", "use_current_attachment": True}
        )
    )
    assert "error" in res
    assert len(media_env.fake.images.edit_calls) == 0


def test_edit_with_mask_media_id(media_env):
    source = ingest._ingest_bytes(_png("red"), source="upload")
    mask = ingest._ingest_bytes(_png("white"), source="upload")
    res = json.loads(
        _edit_tool().invoke(
            {
                "prompt": "replace",
                "source_media_id": source["media_id"],
                "mask_media_id": mask["media_id"],
            }
        )
    )
    assert "error" not in res
    call = media_env.fake.images.edit_calls[0]
    assert "mask" in call


def test_edit_rejects_mask_dimension_mismatch(media_env):
    source = ingest._ingest_bytes(_png("red"), source="upload")
    mask = ingest._ingest_bytes(_png("white", (3, 3)), source="upload")
    before = len(media_env.fake.images.edit_calls)
    res = json.loads(
        _edit_tool().invoke(
            {
                "prompt": "x",
                "source_media_id": source["media_id"],
                "mask_media_id": mask["media_id"],
            }
        )
    )
    assert "error" in res
    assert len(media_env.fake.images.edit_calls) == before


def test_edit_rejects_non_png_mask(media_env):
    buf = io.BytesIO()
    Image.new("RGB", (6, 4), "white").save(buf, format="JPEG")
    source = ingest._ingest_bytes(_png("red"), source="upload")
    mask = ingest._ingest_bytes(buf.getvalue(), source="upload")
    res = json.loads(
        _edit_tool().invoke(
            {
                "prompt": "x",
                "source_media_id": source["media_id"],
                "mask_media_id": mask["media_id"],
            }
        )
    )
    assert "error" in res
    assert len(media_env.fake.images.edit_calls) == 0


def test_ingest_dedup_same_bytes(media_env):
    data = _png("red")
    first = ingest._ingest_bytes(data, source="upload")
    second = ingest._ingest_bytes(data, source="upload")
    assert first["media_id"] == second["media_id"]
    assert _media_count() == 1


def test_ingest_rejects_unsupported_format(media_env):
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="BMP")
    with pytest.raises(ValueError, match="Unsupported input image format"):
        ingest._ingest_bytes(buf.getvalue(), source="upload")


def test_capability_and_output_schema():
    by_key = {d.key: d for d in get_capability_definitions()}
    definition = by_key["image_edit"]
    assert definition.adapter_kind == "registry_tool"
    assert definition.default_approval_policy == "plan_required"
    assert definition.read_only is False
    assert capability_schemas.resolve_input_model("image_edit") is agent_registry.ImageEditInput
    assert capability_schemas.capability_output_schema(
        "image_edit"
    ) is capability_schemas.capability_output_schema("image_generate")


def test_task_adapter_executes_edit(media_env):
    from obsidian_ai_hub.tasks import store as task_store
    from obsidian_ai_hub.tasks.adapters import get_default_executor

    (media_env.inputs / "task.png").write_bytes(_png("red"))
    task = task_store.create_task("edit an image")
    plan = task_store.create_plan(
        task["task_id"],
        {
            "purpose": "edit",
            "steps": [
                {
                    "capability_key": "image_edit",
                    "title": "edit",
                    "target": {},
                    "inputs": {"prompt": "recolor", "source_path": "task.png"},
                    "side_effects": "external image edit",
                }
            ],
            "completion_criteria": "done",
        },
        {"image_edit": "plan_required"},
    )
    result = get_default_executor().execute_step(
        task, plan, 0, plan["plan"]["steps"][0]
    )
    summary = json.loads(result.summary)
    assert summary["images"][0]["media_id"]


def test_migration_v67_columns():
    conn = get_db_connection()
    try:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(generated_media);").fetchall()
        }
    finally:
        conn.close()
    assert {"source", "content_sha256"} <= columns
