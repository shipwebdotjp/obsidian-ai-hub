import sys
from unittest.mock import MagicMock

# Mock dependencies before importing anything else
mock_torch = MagicMock()
mock_torch.backends.mps.is_available.return_value = False
mock_torch.cuda.is_available.return_value = False
sys.modules["torch"] = mock_torch

mock_transformers = MagicMock()
sys.modules["transformers"] = mock_transformers

mock_sentence_transformers = MagicMock()
sys.modules["sentence_transformers"] = mock_sentence_transformers

mock_dotenv = MagicMock()
sys.modules["dotenv"] = mock_dotenv

mock_yaml = MagicMock()
sys.modules["yaml"] = mock_yaml

import pytest
from unittest.mock import patch
from pathlib import Path
from obsidian_ai_hub.utils.simple_sbert_embeddings import SimpleSbertEmbeddings
from obsidian_ai_hub.utils import config

@pytest.fixture
def mock_transformers_calls():
    with patch("obsidian_ai_hub.utils.simple_sbert_embeddings.AutoTokenizer") as mock_tokenizer, \
         patch("obsidian_ai_hub.utils.simple_sbert_embeddings.AutoModel") as mock_model:
        yield mock_tokenizer, mock_model

@pytest.fixture
def mock_sentence_transformer_calls():
    with patch("obsidian_ai_hub.utils.simple_sbert_embeddings.SentenceTransformer") as mock_st:
        yield mock_st

def test_init_local_success(mock_transformers_calls, tmp_path, monkeypatch):
    mock_tokenizer, mock_model = mock_transformers_calls

    model_name = "test-model"
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / model_name).mkdir()

    monkeypatch.setattr(config, "LOCAL_MODEL_DIR", model_dir)

    # Mock resolve_embedding_dim to avoid further errors
    with patch.object(SimpleSbertEmbeddings, "_resolve_embedding_dim", return_value=768):
        embedder = SimpleSbertEmbeddings(model_name=model_name)

    assert embedder.model_name == model_name
    assert not embedder.allow_network_fallback

    mock_tokenizer.from_pretrained.assert_called_once()
    args, kwargs = mock_tokenizer.from_pretrained.call_args
    assert args[0] == str(model_dir / model_name)
    assert kwargs["local_files_only"] is True

def test_init_local_fail_no_fallback(mock_transformers_calls, tmp_path, monkeypatch):
    mock_tokenizer, mock_model = mock_transformers_calls
    mock_tokenizer.from_pretrained.side_effect = Exception("Not found")

    model_name = "test-model"
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / model_name).mkdir()

    monkeypatch.setattr(config, "LOCAL_MODEL_DIR", model_dir)

    with pytest.raises(RuntimeError) as excinfo:
        SimpleSbertEmbeddings(model_name=model_name, allow_network_fallback=False)

    assert "Failed to load local model" in str(excinfo.value)
    mock_tokenizer.from_pretrained.assert_called_once()

def test_init_local_fail_with_fallback_success(mock_transformers_calls, tmp_path, monkeypatch):
    mock_tokenizer, mock_model = mock_transformers_calls

    # First call (local) fails, second call (network) succeeds
    mock_tokenizer.from_pretrained.side_effect = [Exception("Local fail"), MagicMock()]

    model_name = "test-model"
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / model_name).mkdir()

    monkeypatch.setattr(config, "LOCAL_MODEL_DIR", model_dir)

    with patch.object(SimpleSbertEmbeddings, "_resolve_embedding_dim", return_value=768):
        embedder = SimpleSbertEmbeddings(model_name=model_name, allow_network_fallback=True)

    assert mock_tokenizer.from_pretrained.call_count == 2
    # Local attempt
    args0, kwargs0 = mock_tokenizer.from_pretrained.call_args_list[0]
    assert kwargs0["local_files_only"] is True
    # Network attempt
    args1, kwargs1 = mock_tokenizer.from_pretrained.call_args_list[1]
    assert args1[0] == model_name
    assert kwargs1["local_files_only"] is False

def test_init_no_local_no_fallback(mock_transformers_calls, tmp_path, monkeypatch):
    model_name = "test-model"
    monkeypatch.setattr(config, "LOCAL_MODEL_DIR", tmp_path / "non-existent")

    with pytest.raises(RuntimeError) as excinfo:
        SimpleSbertEmbeddings(model_name=model_name, allow_network_fallback=False)

    assert "not found locally and network fallback is disabled" in str(excinfo.value)

def test_sentence_transformer_fallback_only_when_allowed(mock_transformers_calls, mock_sentence_transformer_calls, tmp_path, monkeypatch):
    mock_tokenizer, _ = mock_transformers_calls
    mock_tokenizer.from_pretrained.side_effect = Exception("Transformers fail")

    model_name = "test-model"
    monkeypatch.setattr(config, "LOCAL_MODEL_DIR", None)

    # allow_network_fallback=False -> Should raise RuntimeError immediately
    with pytest.raises(RuntimeError) as excinfo:
        SimpleSbertEmbeddings(model_name=model_name, allow_network_fallback=False)
    assert "not found locally and network fallback is disabled" in str(excinfo.value)
    mock_sentence_transformer_calls.assert_not_called()

    # allow_network_fallback=True -> Should try SentenceTransformer
    with patch.object(SimpleSbertEmbeddings, "_resolve_embedding_dim", return_value=768):
        SimpleSbertEmbeddings(model_name=model_name, allow_network_fallback=True)
    mock_sentence_transformer_calls.assert_called_once()
