"""Multi-Vault Phase 2: per-Vault file ops, search fan-out, sync contracts."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.web.services import vault as vault_service


def test_per_vault_write_read_isolation():
    r_main = vault_service.write_vault_file("notes/shared.md", "main-body", vault_id="main")
    r_blog = vault_service.write_vault_file("notes/shared.md", "blog-body", vault_id="blog")
    assert r_main["vault_id"] == "main"
    assert r_blog["vault_id"] == "blog"
    got_main = vault_service.get_vault_file("notes/shared.md", vault_id="main")
    got_blog = vault_service.get_vault_file("notes/shared.md", vault_id="blog")
    assert got_main["content"] == "main-body"
    assert got_blog["content"] == "blog-body"
    assert got_main["vault_id"] == "main"
    assert got_blog["vault_id"] == "blog"


def test_per_vault_list_isolation():
    vault_service.write_vault_file("only-main.md", "x", vault_id="main")
    vault_service.write_vault_file("only-blog.md", "y", vault_id="blog")
    main_files = vault_service.list_vault_files(vault_id="main")
    blog_files = vault_service.list_vault_files(vault_id="blog")
    main_paths = {i["relative_path"] for i in main_files["items"]}
    blog_paths = {i["relative_path"] for i in blog_files["items"]}
    assert "only-main.md" in main_paths
    assert "only-main.md" not in blog_paths
    assert "only-blog.md" in blog_paths
    assert "only-blog.md" not in main_paths
    assert all(i["vault_id"] == "main" for i in main_files["items"])
    assert all(i["vault_id"] == "blog" for i in blog_files["items"])


def test_default_vault_is_primary():
    vault_service.write_vault_file("default-target.md", "hello")
    got = vault_service.get_vault_file("default-target.md")
    assert got["vault_id"] == "main"


def test_unknown_vault_id_rejected():
    with pytest.raises(KeyError):
        vault_service.get_vault_file("notes/x.md", vault_id="unknown")
    with pytest.raises(KeyError):
        vault_service.write_vault_file("notes/x.md", "x", vault_id="unknown")
    with pytest.raises(KeyError):
        vault_service.list_vault_files(vault_id="unknown")


def test_path_traversal_blocked_per_vault():
    with pytest.raises(ValueError):
        vault_service.get_vault_file("../escape.md", vault_id="blog")
    with pytest.raises(ValueError):
        vault_service.write_vault_file("../escape.md", "x", vault_id="blog")


def test_list_vaults_returns_registry():
    result = vault_service.list_vaults()
    ids = sorted(i["vault_id"] for i in result["items"])
    assert ids == ["ai", "blog", "main"]
    assert result["total"] == 3
    primary = [i for i in result["items"] if i["is_primary"]]
    assert len(primary) == 1 and primary[0]["vault_id"] == "main"


def test_search_fans_out_with_vault_labels():
    def fake_search_single(query, k=10, search_mode="hybrid", vault_id=None):
        return json.dumps(
            [
                {
                    "content": f"hit-{vault_id}",
                    "metadata": {"relative_path": "n.md"},
                    "score": 0.9 if vault_id == "main" else 0.5,
                }
            ]
        )

    with patch(
        "obsidian_ai_hub.web.services.vault.obsidian_vault_retriever.search_single_vault",
        side_effect=fake_search_single,
    ):
        result = vault_service.search_vault(q="hello", k=10, vault_ids=["blog", "main"])
    assert result["total"] == 2
    # sorted by score desc: main first
    assert result["items"][0]["metadata"]["vault_id"] == "main"
    assert result["items"][1]["metadata"]["vault_id"] == "blog"
    assert all("vault_name" in h["metadata"] for h in result["items"])


def test_search_partial_failure_degrades():
    def fake_search_single(query, k=10, search_mode="hybrid", vault_id=None):
        if vault_id == "blog":
            return json.dumps({"error": "boom"})
        return json.dumps(
            [{"content": "ok", "metadata": {"relative_path": "n.md"}, "score": 1.0}]
        )

    with patch(
        "obsidian_ai_hub.web.services.vault.obsidian_vault_retriever.search_single_vault",
        side_effect=fake_search_single,
    ):
        result = vault_service.search_vault(q="hello", k=10)
    assert result["total"] >= 1
    assert all(h["metadata"]["vault_id"] != "blog" for h in result["items"])


def test_search_all_fail_raises():
    with patch(
        "obsidian_ai_hub.web.services.vault.obsidian_vault_retriever.search_single_vault",
        return_value=json.dumps({"error": "down"}),
    ):
        with pytest.raises(ValueError):
            vault_service.search_vault(q="hello", k=5)


def test_per_vault_index_paths_are_separated():
    sqlite_main, chroma_main = app_config.vault_index_paths("main")
    sqlite_blog, chroma_blog = app_config.vault_index_paths("blog")
    assert sqlite_main != sqlite_blog
    assert chroma_main != chroma_blog
    assert sqlite_main.parent.name == "main"
    assert sqlite_blog.parent.name == "blog"


def test_index_identity_path_change_requires_rebuild(tmp_path: Path):
    from obsidian_ai_hub import sync_valut

    descriptor = app_config.resolve_vault_descriptor("main")
    sync_valut._write_identity("main", descriptor.path)
    # Same path: no error.
    sync_valut.check_vault_index_identity("main")
    # Simulate a config path change by pointing the registry elsewhere.
    other = tmp_path / "relocated-main"
    other.mkdir()
    new_registry = app_config.validate_vault_registry(
        {
            "vaults": {
                "main": {
                    "path": str(other),
                    "display_name": "Test Personal",
                    "role": "primary",
                    "ai_access": "read",
                },
                "blog": {
                    "path": str(app_config.resolve_vault_descriptor("blog").path),
                    "display_name": "Test Blog",
                    "ai_access": "write",
                },
                "ai": {
                    "path": str(app_config.resolve_vault_descriptor("ai").path),
                    "display_name": "Test AI Workspace",
                    "ai_access": "write",
                },
            }
        }
    )
    with patch.object(app_config, "VAULT_REGISTRY", new_registry):
        with pytest.raises(app_config.VaultIndexStaleError):
            sync_valut.check_vault_index_identity("main")


def test_sync_vaults_partial_failure_continues():
    from obsidian_ai_hub import sync_valut

    calls: list[str] = []

    class FakeReport:
        scanned_files = 1
        new_files = 1
        updated_files = 0
        unchanged_files = 0
        deleted_files = 0
        inserted_chunks = 1
        deleted_chunks = 0

    def fake_sync_one(vault_id: str):
        calls.append(vault_id)
        if vault_id == "blog":
            raise RuntimeError("index down")
        return FakeReport()

    with patch.object(sync_valut, "sync_one_vault", side_effect=fake_sync_one):
        with pytest.raises(SystemExit):
            sync_valut.sync_vaults(["main", "blog", "ai"])
    # All vaults attempted despite the blog failure (sorted input order kept).
    assert calls == ["main", "blog", "ai"]


def test_sync_vaults_defaults_to_all_ids_in_order():
    from obsidian_ai_hub import sync_valut

    seen: list[str] = []

    class FakeReport:
        scanned_files = 0
        new_files = 0
        updated_files = 0
        unchanged_files = 0
        deleted_files = 0
        inserted_chunks = 0
        deleted_chunks = 0

    def fake_sync_one(vault_id: str):
        seen.append(vault_id)
        return FakeReport()

    with patch.object(sync_valut, "sync_one_vault", side_effect=fake_sync_one):
        result = sync_valut.sync_vaults(None)
    assert seen == ["ai", "blog", "main"]
    assert result["failed"] == {}


def test_unknown_vault_sync_fails_closed():
    from obsidian_ai_hub import sync_valut
    from obsidian_ai_hub import rebuild_valut

    with pytest.raises(SystemExit) as excinfo:
        sync_valut.sync_vaults(["nope"])
    assert excinfo.value.code == 1
    with pytest.raises(SystemExit) as excinfo:
        rebuild_valut.rebuild_vaults(["nope"])
    assert excinfo.value.code == 1


def test_corrupt_identity_requires_rebuild():
    from obsidian_ai_hub import sync_valut

    identity_path = app_config.vault_index_identity_path("main")
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(app_config.VaultIndexStaleError):
        sync_valut.check_vault_index_identity("main")


def test_unreadable_identity_requires_rebuild(monkeypatch):
    from obsidian_ai_hub import sync_valut

    identity_path = app_config.vault_index_identity_path("main")
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text("{}", encoding="utf-8")

    def failing_read_text(*args, **kwargs):
        raise OSError("simulated read failure")

    monkeypatch.setattr(Path, "read_text", failing_read_text)
    with pytest.raises(app_config.VaultIndexStaleError, match="unreadable"):
        sync_valut.check_vault_index_identity("main")


def test_unknown_vault_api_returns_400(api_token):
    from fastapi.testclient import TestClient

    from obsidian_ai_hub.web.app import create_app

    app = create_app(host="127.0.0.1", port=0, token=api_token)
    client = TestClient(app, headers={"Authorization": f"Bearer {api_token}"})
    res = client.get("/api/v1/vault-file", params={"path": "a.md", "vault": "nope"})
    assert res.status_code == 400
    res = client.get("/api/v1/vault-files", params={"vault": "nope"})
    assert res.status_code == 400
    res = client.get("/api/v1/vault-search", params={"q": "x", "vault": "nope"})
    assert res.status_code == 400


def test_build_index_uses_per_vault_source_and_storage(monkeypatch):
    from obsidian_ai_hub import sync_valut

    captured: dict = {}

    class FakeIndex:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(sync_valut, "SearchIndex", FakeIndex)
    monkeypatch.setattr(sync_valut, "_prepare_model_cache_dir", lambda: None)
    monkeypatch.setattr(
        sync_valut, "SimpleSbertEmbeddings", lambda **kwargs: object()
    )
    descriptor = app_config.resolve_vault_descriptor("blog")
    sync_valut.build_vault_search_index("blog")
    sources = captured["sources"]
    assert len(sources) == 1
    assert Path(str(sources[0].path)) == descriptor.path
    assert "blog" in captured["sqlite_path"]
    assert "blog" in captured["chroma_path"]
