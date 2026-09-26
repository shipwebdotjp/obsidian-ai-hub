"""Tests for media deletion: parent-linked (session/task/workflow) + manual.

Operation scenario (irreversible file + row delete): deleting a parent removes
only its ``source='generated'`` outputs (rows and files); uploaded/imported
inputs are kept because they can be shared across parents. File unlink is
best-effort and happens before the row delete, so a missing file does not block
the row delete. Manual ``DELETE /api/v1/media/{id}`` removes any row.
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
from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.media import generation, store
from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.workflow import store as workflow_store


def _png(color: str = "green", size: tuple[int, int] = (6, 4)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeImages:
    def generate(self, **kwargs):
        payload = base64.b64encode(_png()).decode("ascii")
        return SimpleNamespace(
            data=[SimpleNamespace(b64_json=payload, revised_prompt=None)]
        )


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
    monkeypatch.setattr(
        generation, "_default_client_factory", lambda: _FakeClient()
    )
    return SimpleNamespace(dir=out, inputs=inputs)


@pytest.fixture
def api_client(api_token: str) -> TestClient:
    return TestClient(create_app(host="127.0.0.1", port=0, token=api_token))


def _save(source: str = "generated", **parents) -> dict:
    image = generation.GeneratedImage(
        data=_png(), mime_type="image/png", output_format="png"
    )
    return store.save_generated_image(
        image, prompt="p", model="m", source=source, **parents
    )


def _path_of(ref: dict) -> Path:
    row = store.get_generated_media(ref["media_id"])
    return Path(app_config.IMAGE_GENERATION_OUTPUT_DIR) / row["relative_path"]


def test_delete_generated_media_for_parent_keeps_inputs(media_env):
    generated = _save("generated", session_id="s1")
    uploaded = _save("upload", session_id="s1")
    generated_path = _path_of(generated)
    assert generated_path.exists()

    removed = store.delete_generated_media_for_parent("session", "s1")

    assert len(removed) == 1
    assert store.get_generated_media(generated["media_id"]) is None
    assert not generated_path.exists()
    assert store.get_generated_media(uploaded["media_id"]) is not None


def test_delete_generated_media_for_parent_unknown_kind(media_env):
    with pytest.raises(ValueError):
        store.delete_generated_media_for_parent("bogus", "x")


def test_delete_media_manual_removes_any_source(media_env):
    uploaded = _save("upload", session_id="s1")
    assert store.delete_media(uploaded["media_id"]) is True
    assert store.get_generated_media(uploaded["media_id"]) is None
    assert store.delete_media(uploaded["media_id"]) is False


def test_best_effort_when_file_missing(media_env):
    generated = _save("generated", task_id="t-missing")
    _path_of(generated).unlink()
    removed = store.delete_generated_media_for_parent("task", "t-missing")
    assert len(removed) == 1
    assert store.get_generated_media(generated["media_id"]) is None


def test_delete_session_removes_generated_media(media_env):
    agent = agent_store.create_agent("Del Agent", "p")
    session = agent_store.create_session(agent["agent_id"])
    sid = session["session_id"]
    generated = _save("generated", session_id=sid)
    uploaded = _save("upload", session_id=sid)
    generated_path = _path_of(generated)
    uploaded_path = _path_of(uploaded)

    assert agent_store.delete_session(sid) is True

    assert store.get_generated_media(generated["media_id"]) is None
    assert not generated_path.exists()
    assert store.get_generated_media(uploaded["media_id"]) is not None
    assert uploaded_path.exists()


def test_task_purge_removes_generated_media(media_env):
    terminal = task_store.create_task("old task")
    live = task_store.create_task("live task")
    terminal_media = _save("generated", task_id=terminal["task_id"])
    live_media = _save("generated", task_id=live["task_id"])
    terminal_path = _path_of(terminal_media)
    live_path = _path_of(live_media)

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE task_agent_tasks SET status = ?, finished_at = ?"
            " WHERE task_id = ?",
            (
                sorted(task_store.TASK_TERMINAL_STATUSES)[0],
                "2000-01-01T00:00:00+00:00",
                terminal["task_id"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    purged = task_store.purge_terminal_tasks(retention_days=1)

    assert purged == 1
    assert store.get_generated_media(terminal_media["media_id"]) is None
    assert not terminal_path.exists()
    assert store.get_generated_media(live_media["media_id"]) is not None
    assert live_path.exists()


def _linear_graph():
    return (
        [
            {"node_id": "n_cap", "node_type": "capability", "config": {}},
            {"node_id": "n_end", "node_type": "terminal", "config": {}},
        ],
        [
            {
                "edge_id": "e1",
                "source_node_id": "n_cap",
                "target_node_id": "n_end",
                "order_index": 0,
            }
        ],
    )


def test_workflow_delete_run_removes_generated_media(media_env):
    workflow = workflow_store.create_workflow("del", inputs_schema={"type": "object"})
    revision = workflow["revision"]
    nodes, edges = _linear_graph()
    workflow_store.set_revision_graph(revision["revision_id"], nodes, edges)
    workflow_store.publish_revision(revision["revision_id"])
    run = workflow_store.create_run(
        workflow["workflow_id"], revision["revision_id"], {}
    )
    workflow_store.claim_run("inst-test")
    workflow_store.transition_run_status(
        run["run_id"], "completed", result_summary="ok"
    )
    generated = _save("generated", workflow_run_id=run["run_id"])
    uploaded = _save("upload", workflow_run_id=run["run_id"])
    generated_path = _path_of(generated)
    uploaded_path = _path_of(uploaded)

    workflow_store.delete_run(run["run_id"])

    assert store.get_generated_media(generated["media_id"]) is None
    assert not generated_path.exists()
    assert store.get_generated_media(uploaded["media_id"]) is not None
    assert uploaded_path.exists()


def _terminal_run() -> dict:
    workflow = workflow_store.create_workflow("del2", inputs_schema={"type": "object"})
    revision = workflow["revision"]
    nodes, edges = _linear_graph()
    workflow_store.set_revision_graph(revision["revision_id"], nodes, edges)
    workflow_store.publish_revision(revision["revision_id"])
    run = workflow_store.create_run(
        workflow["workflow_id"], revision["revision_id"], {}
    )
    workflow_store.claim_run("inst-test")
    workflow_store.transition_run_status(
        run["run_id"], "completed", result_summary="ok"
    )
    run["workflow_id"] = workflow["workflow_id"]
    return run


def test_workflow_purge_removes_generated_media(media_env):
    run = _terminal_run()
    generated = _save("generated", workflow_run_id=run["run_id"])
    generated_path = _path_of(generated)
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE workflow_runs SET finished_at = ? WHERE run_id = ?;",
            ("2000-01-01T00:00:00+00:00", run["run_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    purged = workflow_store.purge_terminal_runs(days=1)

    assert purged == 1
    assert store.get_generated_media(generated["media_id"]) is None
    assert not generated_path.exists()


def test_delete_workflow_removes_run_media(media_env):
    run = _terminal_run()
    generated = _save("generated", workflow_run_id=run["run_id"])
    generated_path = _path_of(generated)

    workflow_store.delete_workflow(run["workflow_id"])

    assert store.get_generated_media(generated["media_id"]) is None
    assert not generated_path.exists()


def test_workflow_context_records_run_id(media_env):
    tool = agent_registry.TOOL_DEFINITIONS["image_generate"][
        "get_tool_with_context"
    ]({"session_id": "s", "run_id": "r", "workflow_run_id": "wrun-1"})
    res = json.loads(tool.invoke({"prompt": "x"}))
    assert "error" not in res
    row = store.get_generated_media(res["images"][0]["media_id"])
    assert row["workflow_run_id"] == "wrun-1"


def test_manual_delete_route(media_env, api_client, api_auth_headers):
    ref = _save("generated", session_id="s1")
    media_id = ref["media_id"]
    media_path = _path_of(ref)
    assert media_path.exists()

    assert api_client.delete(f"/api/v1/media/{media_id}").status_code == 401

    res = api_client.delete(
        f"/api/v1/media/{media_id}", headers=api_auth_headers
    )
    assert res.status_code == 204
    assert store.get_generated_media(media_id) is None
    assert not media_path.exists()

    again = api_client.delete(
        f"/api/v1/media/{media_id}", headers=api_auth_headers
    )
    assert again.status_code == 404


def test_migration_v68_column_and_indexes():
    conn = get_db_connection()
    try:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(generated_media);").fetchall()
        }
        indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(generated_media);").fetchall()
        }
    finally:
        conn.close()
    assert "workflow_run_id" in columns
    assert "idx_generated_media_task_id" in indexes
    assert "idx_generated_media_workflow_run_id" in indexes
