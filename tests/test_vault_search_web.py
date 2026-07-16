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
