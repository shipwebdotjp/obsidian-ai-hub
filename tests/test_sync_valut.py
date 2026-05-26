from __future__ import annotations

from unittest.mock import patch

import pytest
from md_hybrid_search import ConfigMismatchError

from obsidian_ai_hub import sync_valut


def test_build_vault_search_index_uses_configured_values(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_valut.config, "VAULT_INDEX_SQLITE_PATH", tmp_path / "data" / "search.sqlite")
    monkeypatch.setattr(sync_valut.config, "VAULT_INDEX_CHROMA_PATH", tmp_path / "data" / "chroma")
    monkeypatch.setattr(sync_valut.config, "VAULT_INDEX_EMBEDDER_MODEL", "cl-nagoya/ruri-v3-310m")
    monkeypatch.setattr(sync_valut.config, "VAULT_INDEX_COLLECTION_NAME", "documents")
    monkeypatch.setattr(sync_valut.config, "VAULT_PATH", tmp_path / "vault")

    fake_embedder = object()
    fake_index = object()

    with (
        patch("obsidian_ai_hub.sync_valut.SimpleSbertEmbeddings", return_value=fake_embedder) as mock_embedder,
        patch("obsidian_ai_hub.sync_valut.SearchIndex", return_value=fake_index) as mock_index,
    ):
        result = sync_valut.build_vault_search_index()

    assert result is fake_index
    mock_embedder.assert_called_once_with(
        model_name="cl-nagoya/ruri-v3-310m",
    )
    mock_index.assert_called_once()
    kwargs = mock_index.call_args.kwargs
    assert kwargs["collection_name"] == "documents"
    assert kwargs["sources"][0].path == str(tmp_path / "vault")
    assert kwargs["sqlite_path"] == str(tmp_path / "data" / "search.sqlite")
    assert kwargs["chroma_path"] == str(tmp_path / "data" / "chroma")
    assert kwargs["embedder"] is fake_embedder


def test_main_exits_on_config_mismatch(monkeypatch):
    class FakeIndex:
        def sync(self):
            raise ConfigMismatchError("configuration mismatch")

    monkeypatch.setattr(sync_valut, "build_vault_search_index", lambda: FakeIndex())

    with pytest.raises(SystemExit) as excinfo:
        sync_valut.main()

    assert excinfo.value.code == 1
