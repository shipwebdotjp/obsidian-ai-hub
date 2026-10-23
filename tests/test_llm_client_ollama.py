"""Ollama の Thinking 切替 (reasoning -> think) の写像テスト。"""

from unittest.mock import MagicMock, patch

from obsidian_ai_hub.utils import llm_client


def _create_ollama(**kwargs):
    with patch("langchain_ollama.ChatOllama") as mock_chat:
        mock_chat.return_value = MagicMock()
        llm_client.create_ollama_llm(model="qwen3.5:9b", **kwargs)
        assert mock_chat.call_count == 1
        return mock_chat.call_args.kwargs


def test_reasoning_false_is_preserved_as_think_false():
    """``False`` が黙って落とされず ``think=false`` として渡る。"""
    kwargs = _create_ollama(reasoning=False)
    assert kwargs["reasoning"] is False


def test_reasoning_none_string_disables_thinking():
    """合言葉 ``"none"`` は Thinking 無効として ``False`` に正規化される。"""
    kwargs = _create_ollama(reasoning="none")
    assert kwargs["reasoning"] is False


def test_reasoning_none_string_case_and_whitespace_insensitive():
    kwargs = _create_ollama(reasoning="  NONE  ")
    assert kwargs["reasoning"] is False


def test_reasoning_true_and_level_passthrough():
    assert _create_ollama(reasoning=True)["reasoning"] is True
    assert _create_ollama(reasoning="low")["reasoning"] == "low"


def test_reasoning_unset_means_model_default():
    assert "reasoning" not in _create_ollama()
    assert "reasoning" not in _create_ollama(reasoning=None)


def test_langchain_factory_maps_effort_none_to_think_false():
    """``reasoning_effort="none"`` が Ollama で Thinking Off になる。"""
    with patch("langchain_ollama.ChatOllama") as mock_chat:
        mock_chat.return_value = MagicMock()
        llm_client.create_langchain_llm(
            provider="ollama",
            model="qwen3.5:9b",
            temperature=0.7,
            max_tokens=128,
            reasoning_effort="none",
        )
        assert mock_chat.call_args.kwargs["reasoning"] is False


def test_langchain_factory_omits_reasoning_without_effort():
    with patch("langchain_ollama.ChatOllama") as mock_chat:
        mock_chat.return_value = MagicMock()
        llm_client.create_langchain_llm(
            provider="ollama",
            model="qwen3.5:9b",
            temperature=0.7,
            max_tokens=128,
        )
        assert "reasoning" not in mock_chat.call_args.kwargs
