import json
import pytest
import uuid
from fastapi.testclient import TestClient

from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.utils import execution_logger
from obsidian_ai_hub.utils.llm_client import (
    _logged_invoke,
    _logged_ainvoke,
    _logged_astream,
    generate_llm_response_with_tools,
)
from obsidian_ai_hub.agents.runtime import execute_subagent_core
from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator


@pytest.fixture
def loopback_client(monkeypatch, test_memory_db_path, api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


def test_migration_v69_and_old_log_compat(loopback_client, test_memory_db_path):
    """Verify that old rows without tool_calls_json return tool_calls: [] in detail API."""
    conn = execution_logger.get_db_connection()
    call_id = str(uuid.uuid4())
    try:
        conn.execute(
            """
            INSERT INTO llm_call_logs (
                call_id, provider, model, temperature, max_tokens, prompt, response, started_at, status
            )
            VALUES (?, 'openai', 'gpt-4o', 0.7, 1000, 'old prompt', 'old response', '2026-01-01T00:00:00Z', 'succeeded')
            """,
            (call_id,),
        )
        conn.commit()
    finally:
        conn.close()

    res = loopback_client.get(f"/api/v1/execution-logs/llm/{call_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["call_id"] == call_id
    assert data["tool_calls"] == []


def test_sensitive_masking_and_truncation():
    """Verify sensitive key masking in args/result and 20,000 char capping."""
    raw_args = {"api_key": "secret_123", "normal": "hello", "nested": {"token": "tok_xyz"}}
    masked_args = execution_logger.mask_sensitive_dict(raw_args)
    assert masked_args["api_key"] == "********"
    assert masked_args["normal"] == "hello"
    assert masked_args["nested"]["token"] == "********"

    # JSON string result masking
    json_result_str = json.dumps({"secret_data": "shh", "user_password": "p1", "info": "ok"})
    processed_res = execution_logger.process_tool_call_result(json_result_str)
    assert "********" in processed_res
    assert "user_password" in processed_res

    # Over 20,000 char capping
    large_str = "A" * 25000
    capped_res = execution_logger.process_tool_call_result(large_str)
    assert len(capped_res) <= 20000
    assert "...（保存表示用に 20,000 文字で省略）" in capped_res


def test_tool_call_statuses_and_update_helper(loopback_client, test_memory_db_path):
    """Verify storing and updating tool calls with various statuses via execution_logger."""
    call_id = str(uuid.uuid4())
    initial_tool_calls = [
        {
            "call_id": "tc_1",
            "provider_call_id": "p_tc_1",
            "tool_name": "vault_read_file",
            "args": {"path": "Notes/test.md", "token": "secret_abc"},
            "status": "requested",
        },
        {
            "call_id": "tc_2",
            "provider_call_id": "p_tc_2",
            "tool_name": "ask_user",
            "args": {"questions": [{"id": "q1", "text": "Are you sure?"}]},
            "status": "requested",
        },
    ]

    execution_logger.start_llm_call(
        call_id=call_id,
        run_id=None,
        provider="openai",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=1000,
        prompt="Test prompt",
        tool_calls=initial_tool_calls,
    )

    # Check status right after start
    detail = execution_logger.get_llm_call_detail(call_id)
    assert detail is not None
    assert len(detail["tool_calls"]) == 2
    assert detail["tool_calls"][0]["status"] == "requested"
    assert detail["tool_calls"][0]["args"]["token"] == "********"

    # Update statuses
    updated_tool_calls = [
        {
            "call_id": "tc_1",
            "provider_call_id": "p_tc_1",
            "tool_name": "vault_read_file",
            "args": {"path": "Notes/test.md", "token": "secret_abc"},
            "status": "succeeded",
            "result": "File content here",
        },
        {
            "call_id": "tc_2",
            "provider_call_id": "p_tc_2",
            "tool_name": "ask_user",
            "args": {"questions": [{"id": "q1", "text": "Are you sure?"}]},
            "status": "succeeded",
            "result": json.dumps({"hitl_run_id": "hitl_123"}),
        },
        {
            "call_id": "tc_3",
            "provider_call_id": "p_tc_3",
            "tool_name": "unpermitted_tool",
            "args": {},
            "status": "skipped",
            "error": "Tool not permitted by policy",
        },
    ]

    execution_logger.update_llm_call_tool_calls(call_id, updated_tool_calls)
    execution_logger.succeed_llm_call(
        call_id=call_id,
        response="Final LLM answer",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        finish_reason="stop",
        tool_calls=updated_tool_calls,
    )

    # API detail request
    res = loopback_client.get(f"/api/v1/execution-logs/llm/{call_id}")
    assert res.status_code == 200
    data = res.json()
    assert len(data["tool_calls"]) == 3
    tc1 = data["tool_calls"][0]
    assert tc1["tool_name"] == "vault_read_file"
    assert tc1["status"] == "succeeded"
    assert tc1["result"] == "File content here"

    tc2 = data["tool_calls"][1]
    assert tc2["tool_name"] == "ask_user"
    assert tc2["status"] == "succeeded"
    assert tc2["result"] == '{"hitl_run_id": "hitl_123"}'

    tc3 = data["tool_calls"][2]
    assert tc3["tool_name"] == "unpermitted_tool"
    assert tc3["status"] == "skipped"
    assert tc3["error"] == "Tool not permitted by policy"


@pytest.mark.anyio
async def test_coding_coordinator_run_id_null(test_memory_db_path, monkeypatch):
    """Verify Coding Coordinator LLM calls explicitly set run_id=None."""
    fake_cmd_run_id = f"cmd_run_{uuid.uuid4().hex[:8]}"
    execution_logger.current_run_id.set(fake_cmd_run_id)

    class FakeLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            from langchain_core.messages import AIMessage
            return AIMessage(content="<final_report>Task completed.</final_report>")

    orch = CodingOrchestrator()
    monkeypatch.setattr("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", lambda **kwargs: FakeLLM())

    events = []
    async for evt in orch.generate_response_events(
        history=[],
        repo_path="/fake/repo",
        backend_name="opencode",
    ):
        events.append(evt)

    # Read latest LLM call log
    conn = execution_logger.get_db_connection()
    try:
        cur = conn.execute("SELECT * FROM llm_call_logs ORDER BY started_at DESC LIMIT 1")
        row = cur.fetchone()
        assert row is not None
        # MUST BE NULL
        assert row["run_id"] is None
    finally:
        conn.close()


@pytest.mark.anyio
async def test_generate_llm_response_with_tools_logging(test_memory_db_path, monkeypatch):
    """Verify tool calls in generate_llm_response_with_tools are logged into llm_call_logs."""
    from langchain_core.tools import tool

    @tool
    def sample_tool(query: str) -> str:
        """Sample tool for testing."""
        return f"result for {query}"

    class FakeLLM:
        def __init__(self):
            self.turn = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            from langchain_core.messages import AIMessage
            self.turn += 1
            if self.turn == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{"id": "call_1", "name": "sample_tool", "args": {"query": "test_q", "api_key": "secret"}}],
                )
            return AIMessage(content="Final answer from LLM.")

    monkeypatch.setattr("obsidian_ai_hub.utils.llm_client.create_langchain_llm", lambda **kwargs: FakeLLM())

    res = generate_llm_response_with_tools(
        provider="openai",
        model="gpt-4o",
        prompt="Execute sample tool",
        tools=[sample_tool],
    )
    assert res == "Final answer from LLM."

    conn = execution_logger.get_db_connection()
    try:
        cur = conn.execute("SELECT * FROM llm_call_logs ORDER BY started_at ASC")
        rows = [dict(r) for r in cur.fetchall()]
        assert len(rows) >= 1
        first_call = rows[0]
        tc_json = first_call["tool_calls_json"]
        parsed = json.loads(tc_json)
        assert len(parsed) == 1
        assert parsed[0]["tool_name"] == "sample_tool"
        assert parsed[0]["status"] == "succeeded"
        assert parsed[0]["args"]["api_key"] == "********"
        assert "result for test_q" in parsed[0]["result"]
    finally:
        conn.close()


@pytest.mark.anyio
async def test_subagent_tool_calls_logging(test_memory_db_path, monkeypatch):
    """Verify subagent execution logs tool calls to llm_call_logs."""
    agent_data = {
        "agent_id": "sub_agent_1",
        "name": "SubAgent",
        "system_prompt": "You are a subagent.",
        "provider": "openai",
        "model": "gpt-4o",
        "tool_ids": [],
    }

    class FakeLLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            from langchain_core.messages import AIMessage
            return AIMessage(content="Subagent final answer.")

    monkeypatch.setattr("obsidian_ai_hub.agents.runtime.create_langchain_llm", lambda **kwargs: FakeLLM())

    trusted_ctx = {
        "agent_id": "sub_agent_1",
        "session_id": "sess_1",
        "run_id": "run_1",
    }

    res = execute_subagent_core(
        agent=agent_data,
        task="Do subtask",
        trusted_ctx=trusted_ctx,
        depth=1,
    )
    assert res["status"] == "succeeded"
    assert res["final_answer"] == "Subagent final answer."

    conn = execution_logger.get_db_connection()
    try:
        cur = conn.execute("SELECT * FROM llm_call_logs ORDER BY started_at DESC LIMIT 1")
        row = cur.fetchone()
        assert row is not None
        assert row["status"] == "succeeded"
    finally:
        conn.close()
