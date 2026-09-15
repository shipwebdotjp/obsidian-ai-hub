"""Tests for ACP Client Backend, launch profiles, session contracts, and ACP service integration."""

import asyncio
import json
import sqlite3
import threading
import pytest
from unittest.mock import MagicMock, patch

from obsidian_ai_hub.coding import acp, service, store
from obsidian_ai_hub.database import get_db_connection


def test_acp_launch_profile():
    p_codex = acp.AcpLaunchProfile.get_profile("codex")
    assert p_codex.profile_id == "codex_acp"
    assert p_codex.backend_name == "codex"
    assert p_codex.supports_resume is False

    p_opencode = acp.AcpLaunchProfile.get_profile("opencode")
    assert p_opencode.profile_id == "opencode_acp"
    assert p_opencode.backend_name == "opencode"
    assert p_opencode.argv == [
        p_opencode.executable, "acp", "--hostname", "127.0.0.1", "--port", "0",
    ]

    with pytest.raises(ValueError):
        acp.AcpLaunchProfile.get_profile("unknown")


def test_acp_codex_argv_override(monkeypatch):
    import json as _json

    monkeypatch.setenv("CODING_CODEX_ACP_PATH", "node")
    monkeypatch.setenv(
        "CODING_CODEX_ACP_ARGV", _json.dumps(["/pinned/codex-acp/dist/index.js"])
    )
    p = acp.AcpLaunchProfile.get_profile("codex")
    assert p.executable == "node"
    assert p.argv == ["node", "/pinned/codex-acp/dist/index.js"]

    monkeypatch.setenv("CODING_CODEX_ACP_ARGV", "not-json")
    with pytest.raises(ValueError):
        acp.AcpLaunchProfile.get_profile("codex")


def test_acp_connection_json_rpc():
    conn = acp.AcpConnection(argv=["echo"], cwd="/tmp")
    conn._send = MagicMock()

    # Test request ID generation and send
    rid = conn.send_request_async("test_method", {"key": "value"})
    assert rid == 1
    conn._send.assert_called_with(
        {"jsonrpc": "2.0", "id": 1, "method": "test_method", "params": {"key": "value"}}
    )

    # Test notification
    conn.notify("test_notify", {"a": 1})
    conn._send.assert_called_with(
        {"jsonrpc": "2.0", "method": "test_notify", "params": {"a": 1}}
    )


def test_acp_handle_permission_request_allow():
    profile = acp.AcpLaunchProfile.get_profile("codex")
    client = acp.AcpClientBackend(profile)
    mock_conn = MagicMock()

    req = {
        "id": 10,
        "method": "session/request_permission",
        "params": {
            "options": [
                {"option_id": "deny", "label": "Deny"},
                {"option_id": "allow", "label": "Allow"},
            ]
        },
    }

    allowed, msg = client._handle_permission_request(req, mock_conn)
    assert allowed is True
    mock_conn.respond.assert_called_once_with(
        10, {"outcome": "allow", "selected_option_id": "allow", "option_id": "allow"}
    )


def test_acp_handle_permission_request_unhandled_raises():
    profile = acp.AcpLaunchProfile.get_profile("codex")
    client = acp.AcpClientBackend(profile)
    mock_conn = MagicMock()

    req = {
        "id": 11,
        "method": "session/request_permission",
        "params": {
            "options": [
                {"option_id": "custom_option", "label": "Custom Option"},
            ]
        },
    }

    with pytest.raises(acp.AcpPermissionRejectedError):
        client._handle_permission_request(req, mock_conn)

    mock_conn.respond_error.assert_called_once_with(
        11, -32601, "Permission denied by client policy"
    )


def test_acp_execute_turn_mocked_success():
    profile = acp.AcpLaunchProfile.get_profile("codex")
    client = acp.AcpClientBackend(profile)

    with patch.object(acp.AcpConnection, "start"), \
         patch.object(acp.AcpConnection, "is_alive", return_value=True), \
         patch.object(acp.AcpConnection, "terminate", return_value=0), \
         patch.object(acp.AcpConnection, "notify"), \
         patch.object(acp.AcpClientBackend, "initialize", return_value={"protocol_version": 1, "capabilities": {"sessionCapabilities": {"resume": {}}}}):

        def fake_request(method, params, timeout=60.0):
            if method == "session/resume":
                assert params["sessionId"] == "acp_sess_123"
                assert params["cwd"] == "/tmp"
                assert params["mcpServers"] == []
                return {"status": "ok"}
            elif method == "session/new":
                return {"sessionId": "acp_sess_123"}
            return {}

        def fake_send_async(method, params):
            if method == "session/prompt":
                assert params["sessionId"] == "acp_sess_123"
                assert params["prompt"] == [{"type": "text", "text": "Hello ACP"}]
            return 99

        def fake_wait_for_resp(rid, timeout):
            return {"result": {"output": "ACP turn output", "stop_reason": "end_turn"}}

        with patch.object(acp.AcpConnection, "request", side_effect=fake_request), \
             patch.object(acp.AcpConnection, "send_request_async", side_effect=fake_send_async), \
             patch.object(acp.AcpConnection, "wait_for_response", side_effect=fake_wait_for_resp):

            res = client.execute_turn(
                repo_path="/tmp",
                prompt="Hello ACP",
                acp_session_id="acp_sess_123",
            )

            assert res.acp_session_id == "acp_sess_123"
            assert res.output == "ACP turn output"
            assert res.exit_code == 0
            assert res.stop_reason == "end_turn"
            assert res.cancelled is False


def test_acp_resume_failure_falls_back_to_new():
    """A failed session/resume recreates the session and records the reason."""
    profile = acp.AcpLaunchProfile.get_profile("opencode")
    client = acp.AcpClientBackend(profile)
    calls = []

    with patch.object(acp.AcpConnection, "start"), \
         patch.object(acp.AcpConnection, "is_alive", return_value=True), \
         patch.object(acp.AcpConnection, "terminate", return_value=0), \
         patch.object(acp.AcpConnection, "notify"), \
         patch.object(acp.AcpClientBackend, "initialize", return_value={"protocol_version": 1, "capabilities": {"sessionCapabilities": {"resume": {}}}}):

        def fake_request(method, params, timeout=60.0):
            calls.append(method)
            if method == "session/resume":
                raise acp.AcpError("RPC error on session/resume: no rollout found")
            elif method == "session/new":
                assert params == {"cwd": "/tmp", "mcpServers": []}
                return {"sessionId": "acp_sess_new"}
            return {}

        with patch.object(acp.AcpConnection, "request", side_effect=fake_request), \
              patch.object(acp.AcpConnection, "send_request_async", return_value=99), \
              patch.object(acp.AcpConnection, "wait_for_response", return_value={"result": {"stopReason": "end_turn"}}):

            res = client.execute_turn(
                repo_path="/tmp",
                prompt="Hello",
                acp_session_id="acp_sess_old",
            )

            assert res.acp_session_id == "acp_sess_new"
            assert res.session_recreated is True
            assert "session/resume" in calls and "session/new" in calls


def test_acp_turn_records_typed_updates_and_agent_info():
    """session/update kinds are classified; agent info is kept in diagnostics."""
    profile = acp.AcpLaunchProfile.get_profile("opencode")
    client = acp.AcpClientBackend(profile)

    updates = [
        {"method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "hi"}}}},
        {"method": "session/update", "params": {"update": {"sessionUpdate": "tool_call", "toolCallId": "c1"}}},
        {"method": "session/update", "params": {"update": {"sessionUpdate": "usage_update"}}},
        {"method": "_auth/status_update", "params": {"kind": "api-key"}},
    ]

    with patch.object(acp.AcpConnection, "start"), \
         patch.object(acp.AcpConnection, "is_alive", return_value=True), \
         patch.object(acp.AcpConnection, "terminate", return_value=0), \
         patch.object(acp.AcpConnection, "notify"), \
         patch.object(
             acp.AcpClientBackend,
             "initialize",
             return_value={
                 "protocol_version": 1,
                 "agent_info": {"name": "OpenCode", "version": "1.18.31"},
                 "capabilities": {},
             },
         ):

        def fake_request(method, params, timeout=60.0):
            if method == "session/new":
                return {"sessionId": "s1"}
            return {}

        pops = {"n": 0}

        def fake_pop_notifications():
            pops["n"] += 1
            return list(updates) if pops["n"] == 1 else []

        with patch.object(acp.AcpConnection, "request", side_effect=fake_request), \
              patch.object(acp.AcpConnection, "send_request_async", return_value=5), \
              patch.object(
                  acp.AcpConnection,
                  "wait_for_response",
                  return_value={"result": {"stopReason": "end_turn"}},
              ), \
              patch.object(
                  acp.AcpConnection, "pop_notifications", side_effect=fake_pop_notifications
              ), \
              patch.object(acp.AcpConnection, "pop_client_requests", return_value=[]):

            res = client.execute_turn(repo_path="/tmp", prompt="hi")

            assert res.output == "hi"
            assert res.diagnostics["update_kinds"]["agent_message_chunk"] == 1
            assert res.diagnostics["update_kinds"]["tool_call"] == 1
            assert res.diagnostics["update_kinds"]["usage_update"] == 1
            assert res.diagnostics["update_kinds"]["ignored:_auth/status_update"] == 1
            assert res.diagnostics["acp_agent"] == {"name": "OpenCode", "version": "1.18.31"}


def test_acp_agent_version_mismatch_warns(caplog):
    profile = acp.AcpLaunchProfile.get_profile("opencode")
    assert profile.expected_version == "1.18.31"
    client = acp.AcpClientBackend(profile)

    with patch.object(acp.AcpConnection, "start"), \
         patch.object(acp.AcpConnection, "is_alive", return_value=True), \
         patch.object(acp.AcpConnection, "terminate", return_value=0), \
         patch.object(acp.AcpConnection, "notify"), \
         patch.object(
             acp.AcpClientBackend,
             "initialize",
             return_value={
                 "protocol_version": 1,
                 "agent_info": {"name": "OpenCode", "version": "9.99.99"},
                 "capabilities": {},
             },
         ), \
         patch.object(
             acp.AcpConnection, "request", return_value={"sessionId": "s9"}
         ), \
         patch.object(acp.AcpConnection, "send_request_async", return_value=5), \
         patch.object(
             acp.AcpConnection,
             "wait_for_response",
             return_value={"result": {"stopReason": "end_turn"}},
         ), \
         patch.object(acp.AcpConnection, "pop_notifications", return_value=[]), \
         patch.object(acp.AcpConnection, "pop_client_requests", return_value=[]):
        with caplog.at_level("WARNING", logger="obsidian_ai_hub.coding.acp"):
            res = client.execute_turn(repo_path="/tmp", prompt="hi")

    assert res.acp_session_id == "s9"
    assert "differs from pinned" in caplog.text


def test_acp_prompt_error_fails_loudly():
    """Agent-side prompt errors fail the turn instead of empty output."""
    profile = acp.AcpLaunchProfile.get_profile("opencode")
    client = acp.AcpClientBackend(profile)

    with patch.object(acp.AcpConnection, "start"), \
         patch.object(acp.AcpConnection, "is_alive", return_value=True), \
         patch.object(acp.AcpConnection, "terminate", return_value=0), \
         patch.object(acp.AcpConnection, "notify"), \
         patch.object(
             acp.AcpClientBackend,
             "initialize",
             return_value={"protocol_version": 1, "capabilities": {}},
         ), \
         patch.object(
             acp.AcpConnection, "request", return_value={"sessionId": "s1"}
         ), \
         patch.object(acp.AcpConnection, "send_request_async", return_value=5), \
         patch.object(
             acp.AcpConnection,
             "wait_for_response",
             return_value={"error": {"code": -32603, "message": "boom"}},
         ), \
         patch.object(acp.AcpConnection, "pop_notifications", return_value=[]), \
         patch.object(acp.AcpConnection, "pop_client_requests", return_value=[]):

        res = client.execute_turn(repo_path="/tmp", prompt="hi")

    assert res.output == ""
    assert res.error_message is not None and "boom" in res.error_message


def test_acp_stdout_pollution_ignored():
    """Non-JSON stdout lines never break the NDJSON reader."""
    conn = acp.AcpConnection(argv=["true"], cwd="/tmp")
    lines = [
        "[WARN] mDNS enabled but hostname is loopback\n",
        "not json at all\n",
        '{"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ok"}}}}\n',
        "",
    ]
    fake_stdout = MagicMock()
    fake_stdout.readline.side_effect = lines
    fake_stderr = MagicMock()
    fake_stderr.readline.side_effect = [""]
    conn.proc = MagicMock()
    conn.proc.stdout = fake_stdout
    conn.proc.stderr = fake_stderr
    conn._read_stdout()
    notifs = conn.pop_notifications()
    assert len(notifs) == 1
    assert notifs[0]["method"] == "session/update"


def test_worker_acp_transport_end_to_end(tmp_path):
    """Resident worker executes ACP-transport sessions via AcpClientBackend."""
    import subprocess as _subprocess

    from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator
    from obsidian_ai_hub.runs.coding_worker import execute_coding_run

    repo = tmp_path / "acp_repo"
    repo.mkdir()
    _subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    conn = get_db_connection()
    now = "2026-09-15T00:00:00+09:00"
    cur = conn.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status, created_at, updated_at, project_path) "
        "VALUES ('acp-proj', 'ACP Proj', 'personal', 'active', ?, ?, ?)",
        (now, now, str(repo)),
    )
    project_id = cur.lastrowid
    conn.commit()
    conn.close()

    sess = store.create_session(
        project_id=project_id,
        backend="opencode",
        repo_path=str(repo),
        title="ACP Worker Session",
        transport="acp",
    )
    assert sess["transport"] == "acp"

    _, run = store.start_queued_run(sess["session_id"], "do ACP work")
    assert run["transport"] == "acp"

    async def fake_events(*args, **kwargs):
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            yield {"type": "text", "content": "<final_report>done via ACP</final_report>"}
        else:
            yield {
                "type": "text",
                "content": "go\n<cli_request>\ninspect repo\n</cli_request>",
            }

    fake_res = acp.AcpExecutionResult(
        acp_session_id="acp_sess_9",
        output="ACP did it",
        exit_code=0,
        stop_reason="end_turn",
        diagnostics={"acp_version": "1.0"},
    )

    with (
        patch.object(
            CodingOrchestrator, "generate_response_events", side_effect=fake_events
        ),
        patch.object(acp.AcpClientBackend, "execute_turn", return_value=fake_res),
    ):
        asyncio.run(execute_coding_run(run["run_id"]))

    got = store.get_run(run["run_id"])
    assert got["status"] == "completed"
    worker_msgs = [
        m for m in store.list_messages(sess["session_id"]) if m["role"] == "worker"
    ]
    assert worker_msgs and "ACP did it" in worker_msgs[-1]["content"]
    assert store.get_session(sess["session_id"])["acp_session_id"] == "acp_sess_9"
    events = store.list_run_events(run["run_id"], 0, 200)
    assert any(e["event_type"] == "worker_done" for e in events)


def test_acp_service_turn_stream_integration(monkeypatch, tmp_path):
    asyncio.run(_async_test_acp_service_turn_stream_integration(monkeypatch, tmp_path))

async def _async_test_acp_service_turn_stream_integration(monkeypatch, tmp_path):
    # Setup test DB tables and a project
    conn = get_db_connection()
    now = "2026-09-15T00:00:00+09:00"
    conn.execute(
        "INSERT INTO projects (project_id, normalized_name, display_name, domain, status, created_at, updated_at, project_path) "
        "VALUES (999, 'test_proj', 'Test Proj', 'personal', 'active', ?, ?, ?)",
        (now, now, str(tmp_path)),
    )
    conn.commit()
    conn.close()

    # Initialize a Git repo at tmp_path
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True)

    # Create ACP session
    sess = store.create_session(
        project_id=999,
        backend="codex",
        repo_path=str(tmp_path),
        title="ACP Session",
        transport="acp",
        acp_session_id="acp_existing_id",
    )
    session_id = sess["session_id"]
    assert sess["transport"] == "acp"

    # Mock Orchestrator to emit <cli_request>
    async def mock_events(*args, **kwargs):
        yield {"type": "text", "content": "I will run a command.\n<cli_request>\necho ACP Test\n</cli_request>"}

    monkeypatch.setattr(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response_events",
        mock_events,
    )

    # Mock AcpClientBackend.execute_turn
    fake_acp_res = acp.AcpExecutionResult(
        acp_session_id="acp_existing_id",
        output="Command executed via ACP",
        exit_code=0,
        stop_reason="end_turn",
        diagnostics={"acp_version": "1.0"},
    )

    monkeypatch.setattr(
        "obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn",
        lambda *args, **kwargs: fake_acp_res,
    )

    events = []
    async for sse in service.run_coding_turn_stream(session_id, "Do ACP task"):
        for line in sse.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    event_types = [e.get("event") for e in events]
    assert "start" in event_types
    assert "orchestrator_message" in event_types
    assert "cli_request" in event_types
    assert "worker_start" in event_types
    assert "worker_done" in event_types
    assert "done" in event_types

    worker_done_event = next(e for e in events if e.get("event") == "worker_done")
    assert worker_done_event["message"]["content"] == "Command executed via ACP"
    assert worker_done_event["stop_reason"] == "end_turn"

    # Verify run persisted transport and ACP metadata
    runs = store.list_runs_for_session(session_id)
    assert len(runs) == 1
    assert runs[0]["transport"] == "acp"
    assert runs[0]["acp_session_id"] == "acp_existing_id"
