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
    assert p_codex.supports_resume is True

    p_opencode = acp.AcpLaunchProfile.get_profile("opencode")
    assert p_opencode.profile_id == "opencode_acp"
    assert p_opencode.backend_name == "opencode"
    assert p_opencode.argv == [p_opencode.executable, "acp"]

    with pytest.raises(ValueError):
        acp.AcpLaunchProfile.get_profile("unknown")


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
         patch.object(acp.AcpClientBackend, "initialize", return_value={"protocol_version": "1.0", "capabilities": {"resume": True}}):

        def fake_request(method, params, timeout=60.0):
            if method == "session/resume":
                return {"status": "ok"}
            elif method == "session/new":
                return {"sessionId": "acp_sess_123"}
            return {}

        def fake_send_async(method, params):
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
