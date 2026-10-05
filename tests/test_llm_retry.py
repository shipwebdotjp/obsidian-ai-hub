"""Retry behavior for transient LLM provider failures.

Covers the summerize_day outage where an OpenAI-compatible 5xx
(``InternalServerError``) aborted the daily structured-record generation:
- each transient class (5xx / 429 / timeout / connection) is retried,
- a mocked 500 succeeds after a retry,
- retry exhaustion leaves every llm_call_log and the command run in a
  terminal state with provider-inquiry diagnostics persisted.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage

from obsidian_ai_hub.utils import execution_logger, llm_client

_PROVIDER = "opencode_go"
_MODEL = "deepseek-v4.1-flash"
_REQUEST_ID = "req_retry_case_500"


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://opencode.ai/zen/go/v1/chat/completions")


def _server_error(
    *,
    status: int = 500,
    message: str = "Unknown Error",
    request_id: str = _REQUEST_ID,
    body=None,
):
    response = httpx.Response(
        status,
        request=_request(),
        headers={"x-request-id": request_id},
        content=json.dumps({"error": {"message": message}}),
    )
    payload = {"error": {"message": message}} if body is None else body
    return openai.InternalServerError(message, response=response, body=payload)


def _rate_limit_error(*, request_id: str = "req_retry_case_429"):
    response = httpx.Response(
        429,
        request=_request(),
        headers={"x-request-id": request_id},
        content=json.dumps({"error": {"message": "rate limited"}}),
    )
    return openai.RateLimitError("rate limited", response=response, body=None)


def _bare_internal_server_error() -> Exception:
    """An ``InternalServerError`` without ``status_code`` (wrapped/re-raised)."""
    return type("InternalServerError", (Exception,), {})("Unknown Error")


def _diagnostics_from_message(message: str) -> dict:
    marker = "[llm-diagnostics] "
    assert marker in message
    return json.loads(message.split(marker, 1)[1])


@pytest.mark.parametrize(
    ("failure", "expected_kind"),
    [
        (_server_error(), "server_error"),
        (_bare_internal_server_error(), "server_error"),
        (_rate_limit_error(), "rate_limit"),
        (openai.APITimeoutError(request=_request()), "timeout"),
        (openai.APIConnectionError(request=_request()), "connection"),
    ],
    ids=[
        "server_error",
        "server_error_without_status",
        "rate_limit",
        "timeout",
        "connection",
    ],
)
@patch("obsidian_ai_hub.utils.llm_client.config.ensure_external_allowed")
def test_transient_llm_errors_are_retried_then_succeed(
    mock_ensure, failure, expected_kind, test_memory_db_path, monkeypatch
):
    """Each transient error class is retried and recovery is logged."""
    monkeypatch.setattr(llm_client, "LLM_RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(llm_client, "LLM_RETRY_INITIAL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(llm_client, "LLM_RETRY_MAX_DELAY_SECONDS", 0.0)

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [
        failure,
        AIMessage(
            content="recovered",
            response_metadata={"finish_reason": "stop"},
        ),
    ]

    factory = patch(
        "obsidian_ai_hub.utils.llm_client.create_langchain_llm",
        return_value=mock_llm,
    )
    with factory:
        result = llm_client.generate_llm_response(
            provider=_PROVIDER, model=_MODEL, prompt="p"
        )

    assert result == "recovered"
    assert mock_llm.invoke.call_count == 2

    items, total = execution_logger.list_execution_logs(kind="llm")
    assert total == 2
    by_status = {item["status"] for item in items}
    assert by_status == {"failed", "succeeded"}

    failed = next(item for item in items if item["status"] == "failed")
    detail = execution_logger.get_llm_call_detail(failed["id"])
    diagnostics = _diagnostics_from_message(detail["exception_message"])
    assert diagnostics["provider"] == _PROVIDER
    assert diagnostics["model"] == _MODEL
    assert diagnostics["attempt"] == 1
    assert diagnostics["error_kind"] == expected_kind
    if diagnostics["http_status"] is not None:
        assert diagnostics["http_status"] in (500, 429)


@patch("obsidian_ai_hub.utils.llm_client.config.ensure_external_allowed")
def test_server_error_exhaustion_leaves_terminal_states(
    mock_ensure, test_memory_db_path, monkeypatch
):
    """Retries are bounded and every log row reaches a terminal state."""
    monkeypatch.setattr(llm_client, "LLM_RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(llm_client, "LLM_RETRY_INITIAL_DELAY_SECONDS", 1.0)
    monkeypatch.setattr(llm_client, "LLM_RETRY_MAX_DELAY_SECONDS", 2.0)
    monkeypatch.setattr(llm_client, "LLM_RETRY_JITTER_RATIO", 0.0)

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = _server_error(request_id="req_exhaust_500")

    run_id = str(uuid.uuid4())
    execution_logger.start_command_run(
        run_id, "summerize_day", {"day_date": "2026-10-03"}
    )
    token = execution_logger.current_run_id.set(run_id)
    try:
        factory = patch(
            "obsidian_ai_hub.utils.llm_client.create_langchain_llm",
            return_value=mock_llm,
        )
        with factory, patch.object(
            llm_client.time, "sleep"
        ) as mock_sleep:
            with pytest.raises(openai.InternalServerError) as excinfo:
                llm_client.generate_llm_response(
                    provider=_PROVIDER, model=_MODEL, prompt="p"
                )
        execution_logger.fail_command_run(run_id, excinfo.value)
    finally:
        execution_logger.current_run_id.reset(token)

    # Bounded, exponential, capped delays: 1s then 2s.
    assert mock_llm.invoke.call_count == 3
    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays == [1.0, 2.0]

    items, total = execution_logger.list_execution_logs(kind="llm")
    assert total == 3
    assert all(item["status"] == "failed" for item in items)

    attempts = []
    for item in items:
        detail = execution_logger.get_llm_call_detail(item["id"])
        assert detail["finished_at"] is not None
        diagnostics = _diagnostics_from_message(detail["exception_message"])
        assert diagnostics["provider"] == _PROVIDER
        assert diagnostics["model"] == _MODEL
        assert diagnostics["error_kind"] == "server_error"
        assert diagnostics["http_status"] == 500
        assert diagnostics["request_id"] == "req_exhaust_500"
        assert diagnostics["max_attempts"] == 3
        attempts.append(diagnostics["attempt"])
    assert sorted(attempts) == [1, 2, 3]

    detail = execution_logger.get_command_run_detail(run_id)
    assert detail["status"] == "failed"
    assert detail["finished_at"] is not None
    assert detail["exception_type"] == "InternalServerError"
    assert len(detail["llm_calls"]) == 3
    assert all(call["status"] == "failed" for call in detail["llm_calls"])


def test_error_diagnostics_redact_secrets():
    """Stored diagnostics must not leak API keys or tokens."""
    secret_key = "sk-test-redact-abcdefghijklmnop"
    secret_token = "Bearer redactme-abcdefghijklmnopqrst"
    body = {
        "error": {
            "message": "upstream auth failed",
            "api_key": secret_key,
            "auth": secret_token,
        }
    }
    exc = _server_error(body=body, request_id="req_secret_500")

    diagnostics = llm_client._llm_error_diagnostics(
        exc, provider=_PROVIDER, model=_MODEL, attempt=1, max_attempts=3
    )

    assert diagnostics["http_status"] == 500
    assert diagnostics["request_id"] == "req_secret_500"
    assert secret_key not in (diagnostics["response_body"] or "")
    assert secret_token not in (diagnostics["response_body"] or "")
