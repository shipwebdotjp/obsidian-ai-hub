import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def loopback_client(monkeypatch, tmp_path):
    from obsidian_ai_hub.utils import config
    vault_path = tmp_path / "vault"
    vault_path.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "VAULT_PATH", vault_path)
    app = create_app(host="127.0.0.1", port=0, token="")
    return TestClient(app)


def _mock_search_results(items: list[dict]) -> str:
    return json.dumps(items)


def test_vault_search_basic(loopback_client):
    mock_items = [
        {
            "content": "これはテスト本文です",
            "metadata": {
                "collection_name": "documents",
                "file_path": "/vault/test.md",
                "relative_path": "test.md",
                "chunk_index": 0,
                "mtime": 1700000000.0,
                "content_hash": "abc123",
            },
            "score": 0.85,
        }
    ]
    with patch(
        "obsidian_ai_hub.handler.obsidian_vault_retriever.search_obsidian_vault.func",
        return_value=_mock_search_results(mock_items),
    ):
        res = loopback_client.get("/api/v1/vault-search", params={"q": "test", "k": 5, "mode": "hybrid"})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    hit = body["items"][0]
    assert hit["score"] == 0.85
    assert hit["content"] == "これはテスト本文です"
    assert hit["metadata"]["relative_path"] == "test.md"
    assert hit["metadata"]["vault_name"] == "vault"


def test_vault_search_empty(loopback_client):
    with patch(
        "obsidian_ai_hub.handler.obsidian_vault_retriever.search_obsidian_vault.func",
        return_value=_mock_search_results([]),
    ):
        res = loopback_client.get("/api/v1/vault-search", params={"q": "no_match"})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_vault_search_error(loopback_client):
    with patch(
        "obsidian_ai_hub.handler.obsidian_vault_retriever.search_obsidian_vault.func",
        return_value=json.dumps({"error": "index not found"}),
    ):
        res = loopback_client.get("/api/v1/vault-search", params={"q": "test"})
    assert res.status_code == 500
    assert "index not found" in res.json()["detail"]


def test_vault_search_invalid_mode(loopback_client):
    res = loopback_client.get("/api/v1/vault-search", params={"q": "test", "mode": "invalid"})
    assert res.status_code == 400
    assert "mode must be one of" in res.json()["detail"]


def test_vault_search_missing_query(loopback_client):
    res = loopback_client.get("/api/v1/vault-search")
    assert res.status_code == 422


def test_vault_search_token_required():
    app = create_app(host="0.0.0.0", port=0, token="secret-token")
    client = TestClient(app)

    res = client.get("/api/v1/vault-search?q=test")
    assert res.status_code == 401

    res = client.get(
        "/api/v1/vault-search?q=test",
        headers={"Authorization": "Bearer wrong"},
    )
    assert res.status_code == 401

    with patch(
        "obsidian_ai_hub.handler.obsidian_vault_retriever.search_obsidian_vault.func",
        return_value=_mock_search_results([]),
    ):
        res = client.get(
            "/api/v1/vault-search?q=test",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert res.status_code == 200


def test_vault_search_k_limits(loopback_client):
    res = loopback_client.get("/api/v1/vault-search", params={"q": "test", "k": 0})
    assert res.status_code == 422

    res = loopback_client.get("/api/v1/vault-search", params={"q": "test", "k": 100})
    assert res.status_code == 422


def test_vault_search_missing_metadata(loopback_client):
    mock_items = [{"content": "x", "metadata": None, "score": 0.1}]
    with patch(
        "obsidian_ai_hub.handler.obsidian_vault_retriever.search_obsidian_vault.func",
        return_value=_mock_search_results(mock_items),
    ):
        res = loopback_client.get("/api/v1/vault-search", params={"q": "test"})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["metadata"]["vault_name"] == "vault"


def test_vault_file_success(loopback_client, tmp_path):
    vault_path = tmp_path / "vault"
    note_path = vault_path / "test-note.md"
    note_content = "---\ntitle: Hello\n---\n# World"
    note_path.write_text(note_content, encoding="utf-8")

    res = loopback_client.get("/api/v1/vault-file", params={"path": "test-note.md"})
    assert res.status_code == 200
    body = res.json()
    assert body["content"] == note_content
    assert body["relative_path"] == "test-note.md"


def test_vault_file_subdir_success(loopback_client, tmp_path):
    vault_path = tmp_path / "vault"
    sub_dir = vault_path / "daily"
    sub_dir.mkdir(exist_ok=True)
    note_path = sub_dir / "2026-07-16.md"
    note_content = "Subdir note content"
    note_path.write_text(note_content, encoding="utf-8")

    res = loopback_client.get("/api/v1/vault-file", params={"path": "daily/2026-07-16.md"})
    assert res.status_code == 200
    body = res.json()
    assert body["content"] == note_content
    assert body["relative_path"] == "daily/2026-07-16.md"


def test_vault_file_not_found(loopback_client):
    res = loopback_client.get("/api/v1/vault-file", params={"path": "non-existent.md"})
    assert res.status_code == 404


def test_vault_file_non_markdown(loopback_client, tmp_path):
    vault_path = tmp_path / "vault"
    file_path = vault_path / "test.txt"
    file_path.write_text("hello", encoding="utf-8")

    res = loopback_client.get("/api/v1/vault-file", params={"path": "test.txt"})
    assert res.status_code == 400


def test_vault_file_absolute_path(loopback_client):
    res = loopback_client.get("/api/v1/vault-file", params={"path": "/absolute/path.md"})
    assert res.status_code == 400


def test_vault_file_path_traversal(loopback_client):
    res = loopback_client.get("/api/v1/vault-file", params={"path": "../outside.md"})
    assert res.status_code == 400

    res = loopback_client.get("/api/v1/vault-file", params={"path": "subdir/../../outside.md"})
    assert res.status_code == 400


def test_vault_file_symlink_outside(loopback_client, tmp_path):
    import os
    vault_path = tmp_path / "vault"
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("dangerous", encoding="utf-8")

    sym_path = vault_path / "symlink.md"
    try:
        os.symlink(outside_file, sym_path)
    except OSError:
        pytest.skip("Symlinks are not supported on this platform/privilege level")

    res = loopback_client.get("/api/v1/vault-file", params={"path": "symlink.md"})
    assert res.status_code == 400
