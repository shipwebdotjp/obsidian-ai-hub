"""Session-scoped OpenCode model selection (allowlist-only)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENV", "test")

from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.coding import store as coding_store


@pytest.fixture()
def _models_env(monkeypatch):
    monkeypatch.setenv(
        "CODING_OPENCODE_MODELS", "model-alpha,model-beta"
    )
    monkeypatch.setattr(app_config, "CODING_OPENCODE_MODEL", "model-alpha", raising=False)
    yield


def _make_project(tmp_path):

    from obsidian_ai_hub import database as db

    conn = db.get_db_connection()
    cur = conn.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status, project_path, created_at, updated_at)"
        " VALUES ('tproj', 'proj', 'personal', 'active', ?, datetime('now'), datetime('now'))",
        (str(tmp_path),),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def test_allowlist_and_compat(tmp_path, monkeypatch, _models_env):

    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(tmp_path / "m.sqlite3"))
    # Fresh DB file: run migrations including v49
    from obsidian_ai_hub import database as db

    conn = db.get_db_connection()
    conn.close()

    pid = _make_project(tmp_path)

    # Default model when omitted (compat with legacy single-model config)
    s1 = coding_store.create_session(
        project_id=pid, backend="opencode", repo_path=str(tmp_path)
    )
    assert s1["opencode_model"] == "model-alpha"
    assert coding_store.get_effective_session_model(s1) == "model-alpha"
    # Legacy NULL rows fall back to default
    assert coding_store.get_effective_session_model({"opencode_model": None}) == "model-alpha"

    # Explicit allowlisted model persists
    s2 = coding_store.create_session(
        project_id=pid,
        backend="opencode",
        repo_path=str(tmp_path),
        opencode_model="model-beta",
    )
    assert s2["opencode_model"] == "model-beta"

    # Unknown / free-form models rejected
    with pytest.raises(ValueError):
        coding_store.create_session(
            project_id=pid,
            backend="opencode",
            repo_path=str(tmp_path),
            opencode_model="evil-model",
        )
    with pytest.raises(ValueError):
        coding_store.update_session_model(s2["session_id"], "evil-model")

    # Update persists; effective helper reflects it
    updated = coding_store.update_session_model(s2["session_id"], "model-alpha")
    assert updated["opencode_model"] == "model-alpha"
    assert coding_store.get_effective_session_model(updated) == "model-alpha"

    # Model change is accepted during an active run: the in-flight run
    # keeps the model frozen at run start; the next run uses the new model.
    run = coding_store.start_queued_run(
        session_id=s2["session_id"],
        content="hello",
        created_instance_id="test-inst",
    )[1]
    assert run["status"] == "queued"
    frozen_snapshot = dict(coding_store.get_session(s2["session_id"]))
    frozen_run_model = coding_store.get_effective_session_model(frozen_snapshot)
    assert frozen_run_model == "model-alpha"

    changed = coding_store.update_session_model(s2["session_id"], "model-beta")
    assert changed["opencode_model"] == "model-beta"
    # In-flight run's frozen model is unchanged.
    assert coding_store.get_effective_session_model(frozen_snapshot) == "model-alpha"
    # Next message (next run) resolves the new model.
    assert coding_store.get_effective_session_model(changed) == "model-beta"

    # Unlisted / free-form models stay rejected even with an active run.
    with pytest.raises(ValueError):
        coding_store.update_session_model(s2["session_id"], "evil-model")


def test_execute_turn_rejects_unlisted_model(_models_env):
    from obsidian_ai_hub.coding import acp as acp_module

    profile = acp_module.AcpLaunchProfile.get_profile("opencode")
    client = acp_module.AcpClientBackend(profile)

    class _Conn:
        def request(self, *a, **k):
            raise AssertionError("must not reach ACP for unlisted model")

    with pytest.raises(acp_module.AcpError, match="not in the configured model list"):
        client._apply_session_model(_Conn(), "sess", model="evil-model")
