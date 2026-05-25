from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from md_hybrid_search import ConfigMismatchError

from obsidian_ai_hub import sync_valut


def test_prepare_model_cache_dir_uses_local_model_dir(monkeypatch, tmp_path):
    cache_base = tmp_path / "models"
    monkeypatch.setattr(sync_valut.config, "LOCAL_MODEL_DIR", cache_base)
    for env_name in sync_valut.MODEL_CACHE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)

    cache_dir = sync_valut._prepare_model_cache_dir()

    assert cache_dir == cache_base / sync_valut.MODEL_CACHE_SUBDIR
    assert cache_dir.exists()
    for env_name in sync_valut.MODEL_CACHE_ENV_VARS:
        assert os.environ[env_name] == str(cache_dir)


def test_build_vault_search_index_uses_configured_values(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_valut.config, "LOCAL_MODEL_DIR", tmp_path / "models")
    monkeypatch.setattr(sync_valut.config, "VAULT_INDEX_SQLITE_PATH", tmp_path / "data" / "search.sqlite")
    monkeypatch.setattr(sync_valut.config, "VAULT_INDEX_CHROMA_PATH", tmp_path / "data" / "chroma")
    monkeypatch.setattr(sync_valut.config, "VAULT_INDEX_EMBEDDER_MODEL", "cl-nagoya/ruri-v3-310m")
    monkeypatch.setattr(sync_valut.config, "VAULT_INDEX_COLLECTION_NAME", "documents")
    monkeypatch.setattr(sync_valut.config, "VAULT_PATH", tmp_path / "vault")

    fake_embedder = object()
    fake_index = object()

    with (
        patch.object(sync_valut, "SentenceTransformerEmbedder", return_value=fake_embedder) as mock_embedder,
        patch.object(sync_valut, "SearchIndex", return_value=fake_index) as mock_index,
    ):
        result = sync_valut.build_vault_search_index()

    assert result is fake_index
    mock_embedder.assert_called_once_with(
        model_name="cl-nagoya/ruri-v3-310m",
        cache_dir=tmp_path / "models" / sync_valut.MODEL_CACHE_SUBDIR,
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
