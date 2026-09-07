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


def _seed_q_search_data():
    """Seed command + LLM rows carrying unique full-text tokens.

    Returns dict of ids for assertions.
    """
    from obsidian_ai_hub.database import get_db_connection

    run_args = str(uuid.uuid4())
    execution_logger.start_command_run(run_args, "qsearch_cmd", {"note": "alpha-args-token"})
    execution_logger.succeed_command_run(run_args, "beta-summary-token done")

    run_exc = str(uuid.uuid4())
    execution_logger.start_command_run(run_exc, "qsearch_fail_cmd", {})
    try:
        raise RuntimeError("gamma-exc-token boom")
    except RuntimeError as e:
        execution_logger.fail_command_run(run_exc, e)
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE command_runs SET traceback = ? WHERE run_id = ?",
            ("traceback-only-token-cmd line1\ntraceback-only-token-cmd line2", run_exc),
        )
        conn.commit()
    finally:
        conn.close()

    call_ok = str(uuid.uuid4())
    execution_logger.start_llm_call(
        call_id=call_ok,
        run_id=None,
        provider="qsearch-provider",
        model="qsearch-model",
        temperature=0.0,
        max_tokens=10,
        prompt="delta-prompt-token here",
    )
    execution_logger.succeed_llm_call(
        call_id=call_ok,
        response="epsilon-response-token here",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        finish_reason="stop",
    )

    call_fail = str(uuid.uuid4())
    execution_logger.start_llm_call(
        call_id=call_fail,
        run_id=None,
        provider="other-provider",
        model="other-model",
        temperature=0.0,
        max_tokens=10,
        prompt="unrelated prompt",
    )
    try:
        raise ValueError("zeta-llm-exc-token failure")
    except ValueError as e:
        execution_logger.fail_llm_call(call_fail, e)
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE llm_call_logs SET traceback = ? WHERE call_id = ?",
            ("traceback-only-token-llm stack", call_fail),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "run_args": run_args,
        "run_exc": run_exc,
        "call_ok": call_ok,
        "call_fail": call_fail,
    }


def _q_ids(loopback_client, q, **params):
    res = loopback_client.get("/api/v1/execution-logs", params={"q": q, **params})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == len(body["items"])
    return {item["id"] for item in body["items"]}


def test_execution_logs_q_fulltext(loopback_client, test_memory_db_path):
    ids = _seed_q_search_data()

    # LLM prompt / response each match only the LLM row
    assert _q_ids(loopback_client, "delta-prompt-token") == {ids["call_ok"]}
    assert _q_ids(loopback_client, "epsilon-response-token") == {ids["call_ok"]}
    # Command args_json / summary each match only the command row
    assert _q_ids(loopback_client, "alpha-args-token") == {ids["run_args"]}
    assert _q_ids(loopback_client, "beta-summary-token") == {ids["run_args"]}
    # Exception message / traceback
    assert _q_ids(loopback_client, "gamma-exc-token") == {ids["run_exc"]}
    assert _q_ids(loopback_client, "traceback-only-token-cmd") == {ids["run_exc"]}
    assert _q_ids(loopback_client, "zeta-llm-exc-token") == {ids["call_fail"]}
    assert _q_ids(loopback_client, "traceback-only-token-llm") == {ids["call_fail"]}
    # Provider / model still searchable via q
    assert ids["call_ok"] in _q_ids(loopback_client, "qsearch-provider")
    assert ids["call_ok"] in _q_ids(loopback_client, "qsearch-model")


def test_execution_logs_q_literal_wildcards(loopback_client, test_memory_db_path):
    run_pct = str(uuid.uuid4())
    execution_logger.start_command_run(run_pct, "pct_cmd", {})
    execution_logger.succeed_command_run(run_pct, "literal 50% off sale")

    run_decoy = str(uuid.uuid4())
    execution_logger.start_command_run(run_decoy, "decoy_cmd", {})
    execution_logger.succeed_command_run(run_decoy, "literal 50X off sale")

    run_us = str(uuid.uuid4())
    execution_logger.start_command_run(run_us, "us_cmd", {})
    execution_logger.succeed_command_run(run_us, "file_v1_final report")

    run_us_decoy = str(uuid.uuid4())
    execution_logger.start_command_run(run_us_decoy, "us_decoy_cmd", {})
    execution_logger.succeed_command_run(run_us_decoy, "fileXv1_final report")

    run_bs = str(uuid.uuid4())
    execution_logger.start_command_run(run_bs, "bs_cmd", {})
    execution_logger.succeed_command_run(run_bs, "path\\to\\file location")

    # % is literal: must not match the 50X decoy
    assert _q_ids(loopback_client, "50% off") == {run_pct}
    # _ is literal: must not match the fileXv1 decoy
    assert _q_ids(loopback_client, "file_v1") == {run_us}
    # backslash is literal
    assert _q_ids(loopback_client, "path\\to") == {run_bs}


def test_execution_logs_q_combines_with_filters_and(loopback_client, test_memory_db_path):
    ids = _seed_q_search_data()

    # q + kind narrows to the matching kind
    assert _q_ids(loopback_client, "traceback-only-token", kind="command") == {ids["run_exc"]}
    assert _q_ids(loopback_client, "traceback-only-token", kind="llm") == {ids["call_fail"]}

    # q + status narrows by status
    assert _q_ids(loopback_client, "beta-summary-token", status="succeeded") == {ids["run_args"]}
    assert _q_ids(loopback_client, "beta-summary-token", status="failed") == set()

    # q + legacy command param is AND
    assert _q_ids(loopback_client, "beta-summary-token", command="qsearch_cmd") == {ids["run_args"]}
    assert _q_ids(loopback_client, "beta-summary-token", command="qsearch_fail_cmd") == set()
