"""Harness self-tests against fake_agent.py (no network, no secrets, no DB)."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acp_harness import AcpConnection, Redactor, ScenarioRecorder  # noqa: E402


@pytest.fixture
def conn():
    c = AcpConnection(
        argv=[sys.executable, str(Path(__file__).resolve().parent.parent / "fake_agent.py")],
        env={"PATH": "/usr/bin:/bin", "SYSTEMROOT": "x"},
        redactor=Redactor({"K": "super-secret-value-12345"}),
    )
    c.start()
    yield c
    c.terminate()


def test_initialize_and_new_and_prompt(conn):
    rec = ScenarioRecorder()
    init = conn.request(
        "initialize",
        {"protocolVersion": 1, "clientCapabilities": {},
         "clientInfo": {"name": "t", "version": "0"}},
        timeout=10,
    )
    assert init["result"]["protocolVersion"] == 1
    assert init["result"]["agentInfo"]["name"] == "fake-agent"

    new = conn.request("session/new", {"cwd": "/tmp", "mcpServers": []}, timeout=10)
    sid = new["result"]["sessionId"]
    assert sid.startswith("sess_fake_")

    rid = conn.send_request_async(
        "session/prompt",
        {"sessionId": sid, "prompt": [{"type": "text", "text": "hi"}]},
    )
    resp = conn.wait_for_response(rid, timeout=10)
    assert resp is not None and resp["result"]["stopReason"] == "end_turn"
    updates = conn.drain_notifications()
    kinds = [u["params"]["update"]["sessionUpdate"] for u in updates]
    assert "agent_message_chunk" in kinds
    assert conn.non_json_stdout == []
    assert "fake-agent boot" in conn.redacted_stderr()


def test_permission_deny_flow():
    c = AcpConnection(
        argv=[sys.executable, str(Path(__file__).resolve().parent.parent / "fake_agent.py")],
        env={"PATH": "/usr/bin:/bin"},
    )
    c.start()
    try:
        c.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}}, timeout=10)
        new = c.request("session/new", {"cwd": "/tmp", "mcpServers": []}, timeout=10)
        sid = new["result"]["sessionId"]
        rid = c.send_request_async(
            "session/prompt",
            {"sessionId": sid, "prompt": [{"type": "text", "text": "PERMISSION probe"}]},
        )
        deadline = time.monotonic() + 10
        answered = False
        resp = None
        while time.monotonic() < deadline:
            for req in c.drain_client_requests():
                assert req["method"] == "session/request_permission"
                opts = req["params"]["options"]
                reject = next(o["optionId"] for o in opts if o["kind"].startswith("reject"))
                c.respond(rid=req["id"], result={"outcome": {"outcome": "selected", "optionId": reject}})
                answered = True
            if resp is None:
                resp = c.wait_for_response(rid, timeout=0.5)
            if resp is not None and answered:
                break
        assert answered, "expected a permission request from fake agent"
        assert resp is not None and resp["result"]["stopReason"] == "end_turn"
    finally:
        term = c.terminate()
        assert term["exitCode"] is not None
        assert term["orphans"] == []


def test_session_cancel_marks_turn_cancelled():
    c = AcpConnection(
        argv=[sys.executable, str(Path(__file__).resolve().parent.parent / "fake_agent.py")],
        env={"PATH": "/usr/bin:/bin"},
    )
    c.start()
    try:
        c.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}}, timeout=10)
        new = c.request("session/new", {"cwd": "/tmp", "mcpServers": []}, timeout=10)
        sid = new["result"]["sessionId"]
        rid = c.send_request_async(
            "session/prompt",
            {"sessionId": sid, "prompt": [{"type": "text", "text": "slow task"}]},
        )
        time.sleep(0.05)
        c.notify("session/cancel", {"sessionId": sid})
        resp = c.wait_for_response(rid, timeout=10)
        assert resp is not None and resp["result"]["stopReason"] == "cancelled"
    finally:
        c.terminate()


def test_redactor_and_recorder_export():
    red = Redactor({"K": "super-secret-value-12345"})
    assert red("x super-secret-value-12345 y") == "x ***REDACTED*** y"
    rec = ScenarioRecorder()
    rec.sent({"method": "initialize", "params": {"k": "super-secret-value-12345"}})
    exported = rec.export(red)
    assert "super-secret-value-12345" not in json.dumps(exported)
