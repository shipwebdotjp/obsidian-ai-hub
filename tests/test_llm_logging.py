import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage
from obsidian_ai_hub.utils import llm_client, execution_logger


def test_extract_llm_metadata():
    msg = AIMessage(
        content="test response",
        response_metadata={
            "finish_reason": "stop",
            "token_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 15,
                "total_tokens": 25,
            }
        }
    )
    p, c, t, fr = llm_client._extract_llm_metadata(msg)
    assert p == 10
    assert c == 15
    assert t == 25
    assert fr == "stop"


@patch("obsidian_ai_hub.utils.llm_client.config.ensure_external_allowed")
def test_llm_call_logging_success(mock_ensure, test_memory_db_path):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(
        content="success result",
        response_metadata={
            "finish_reason": "stop",
            "token_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            }
        }
    )

    with patch("obsidian_ai_hub.utils.llm_client.create_langchain_llm", return_value=mock_llm):
        res = llm_client.generate_llm_response(
            provider="openai",
            model="gpt-4",
            prompt="my prompt",
            temperature=0.5,
            max_tokens=200,
        )
        assert res == "success result"

    # Verify log in db
    items, total = execution_logger.list_execution_logs(kind="llm")
    assert total == 1
    assert items[0]["name"] == "openai/gpt-4"
    assert items[0]["status"] == "succeeded"

    # Detail
    detail = execution_logger.get_llm_call_detail(items[0]["id"])
    assert detail["prompt"] == "my prompt"
    assert detail["response"] == "success result"
    assert detail["prompt_tokens"] == 10
    assert detail["completion_tokens"] == 20
    assert detail["total_tokens"] == 30
    assert detail["finish_reason"] == "stop"


@patch("obsidian_ai_hub.utils.llm_client.config.ensure_external_allowed")
def test_llm_call_logging_length_warning(mock_ensure, test_memory_db_path, caplog):
    import logging
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(
        content="truncated result",
        response_metadata={
            "finish_reason": "length",
            "token_usage": {
                "prompt_tokens": 5,
                "completion_tokens": 95,
                "total_tokens": 100,
            }
        }
    )

    with (
        patch("obsidian_ai_hub.utils.llm_client.create_langchain_llm", return_value=mock_llm),
        caplog.at_level(logging.WARNING)
    ):
        res = llm_client.generate_llm_response(
            provider="openai",
            model="gpt-4",
            prompt="length prompt",
            temperature=0.5,
            max_tokens=100,
        )
        assert res == "truncated result"

    # Verify warning log was raised
    assert any("LLM output was truncated" in record.message for record in caplog.records)

    # Verify logged in db as succeeded with finish_reason='length'
    items, total = execution_logger.list_execution_logs(kind="llm")
    assert total == 1
    detail = execution_logger.get_llm_call_detail(items[0]["id"])
    assert detail["status"] == "succeeded"
    assert detail["finish_reason"] == "length"


@patch("obsidian_ai_hub.utils.llm_client.config.ensure_external_allowed")
def test_llm_call_logging_failure(mock_ensure, test_memory_db_path):
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API rate limit exceeded")

    with patch("obsidian_ai_hub.utils.llm_client.create_langchain_llm", return_value=mock_llm):
        with pytest.raises(RuntimeError, match="API rate limit exceeded"):
            llm_client.generate_llm_response(
                provider="openai",
                model="gpt-4",
                prompt="fail prompt",
                temperature=0.5,
                max_tokens=100,
            )

    # Verify logged in db as failed
    items, total = execution_logger.list_execution_logs(kind="llm")
    assert total == 1
    detail = execution_logger.get_llm_call_detail(items[0]["id"])
    assert detail["status"] == "failed"
    assert detail["exception_type"] == "RuntimeError"
    assert "API rate limit exceeded" in detail["exception_message"]
    assert detail["traceback"] is not None
