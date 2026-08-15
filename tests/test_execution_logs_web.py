import pytest
import uuid
from fastapi.testclient import TestClient
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.utils import execution_logger


@pytest.fixture
def loopback_client(monkeypatch, test_memory_db_path, api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


def test_execution_logs_apis(loopback_client, test_memory_db_path):
    # 1. Set up some dummy data in our test DB
    run_id = str(uuid.uuid4())
    execution_logger.start_command_run(run_id, "test_action", {"param": 1})

    call_id = str(uuid.uuid4())
    execution_logger.start_llm_call(
        call_id=call_id,
        run_id=run_id,
        provider="openai",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=2000,
        prompt="system prompt\nuser prompt",
    )

    execution_logger.succeed_llm_call(
        call_id=call_id,
        response="hello user",
        prompt_tokens=15,
        completion_tokens=25,
        total_tokens=40,
        finish_reason="stop",
    )

    execution_logger.succeed_command_run(run_id, "done result")

    # 2. Test List API
    res = loopback_client.get("/api/v1/execution-logs")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 2
    # Unified list items
    items = body["items"]
    # Check item details (e.g. prompt/response should NOT be in listing)
    for item in items:
        assert "prompt" not in item
        assert "response" not in item
        assert item["status"] in ("running", "succeeded", "failed")

    # 3. Test List API Filters
    res_cmd = loopback_client.get("/api/v1/execution-logs", params={"kind": "command"})
    assert res_cmd.status_code == 200
    assert all(item["kind"] == "command" for item in res_cmd.json()["items"])

    res_llm = loopback_client.get("/api/v1/execution-logs", params={"kind": "llm"})
    assert res_llm.status_code == 200
    assert all(item["kind"] == "llm" for item in res_llm.json()["items"])

    res_status = loopback_client.get("/api/v1/execution-logs", params={"status": "succeeded"})
    assert res_status.status_code == 200
    assert all(item["status"] == "succeeded" for item in res_status.json()["items"])

    res_name = loopback_client.get("/api/v1/execution-logs", params={"command": "test_action"})
    assert res_name.status_code == 200
    assert any(item["id"] == run_id for item in res_name.json()["items"])

    # 4. Test Command Run Detail API
    res_detail = loopback_client.get(f"/api/v1/execution-logs/commands/{run_id}")
    assert res_detail.status_code == 200
    cmd_detail = res_detail.json()
    assert cmd_detail["run_id"] == run_id
    assert cmd_detail["command"] == "test_action"
    assert cmd_detail["status"] == "succeeded"
    assert cmd_detail["summary"] == "done result"
    # Verify child LLM calls are included
    assert len(cmd_detail["llm_calls"]) == 1
    assert cmd_detail["llm_calls"][0]["call_id"] == call_id
    assert cmd_detail["llm_calls"][0]["total_tokens"] == 40

    # 5. Test LLM Call Detail API
    res_llm_detail = loopback_client.get(f"/api/v1/execution-logs/llm/{call_id}")
    assert res_llm_detail.status_code == 200
    llm_detail = res_llm_detail.json()
    assert llm_detail["call_id"] == call_id
    assert llm_detail["prompt"] == "system prompt\nuser prompt"
    assert llm_detail["response"] == "hello user"
    assert llm_detail["finish_reason"] == "stop"


def test_execution_logs_token_protection():
    app = create_app(host="0.0.0.0", port=0, token="review-token")
    client = TestClient(app)

    # 1. No token -> 401
    res = client.get("/api/v1/execution-logs")
    assert res.status_code == 401

    # 2. Wrong token -> 401
    res = client.get("/api/v1/execution-logs", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401

    # 3. Valid token -> 200
    res = client.get("/api/v1/execution-logs", headers={"Authorization": "Bearer review-token"})
    assert res.status_code == 200
