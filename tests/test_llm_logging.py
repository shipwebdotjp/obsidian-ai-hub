import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage
from obsidian_ai_hub.utils import llm_client, execution_logger


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
def test_llm_detailed_result_returns_call_id_and_finish_reason(
    mock_ensure, test_memory_db_path
):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(
        content="detailed body",
        response_metadata={
            "finish_reason": "length",
            "token_usage": {
                "prompt_tokens": 5,
                "completion_tokens": 7,
                "total_tokens": 12,
            },
        },
    )

    with patch("obsidian_ai_hub.utils.llm_client.create_langchain_llm", return_value=mock_llm):
        res = llm_client.generate_llm_response_detailed(
            provider="openai",
            model="gpt-4",
            prompt="detail prompt",
            temperature=0.5,
            max_tokens=200,
        )
        assert res.text == "detailed body"
        assert res.finish_reason == "length"
        assert res.call_id

    detail = execution_logger.get_llm_call_detail(res.call_id)
    assert detail is not None
    assert detail["finish_reason"] == "length"

    # Existing str API still works and is unaffected.
    mock_llm2 = MagicMock()
    mock_llm2.invoke.return_value = AIMessage(
        content="plain body",
        response_metadata={"finish_reason": "stop"},
    )
    with patch("obsidian_ai_hub.utils.llm_client.create_langchain_llm", return_value=mock_llm2):
        assert (
            llm_client.generate_llm_response(
                provider="openai",
                model="gpt-4",
                prompt="plain prompt",
            )
            == "plain body"
        )


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
