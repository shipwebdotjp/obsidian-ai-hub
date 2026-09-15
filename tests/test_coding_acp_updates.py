"""Tests for ACP session/update normalization into coding run events."""

import asyncio
import subprocess
from unittest.mock import patch

from obsidian_ai_hub.coding import acp, acp_updates, store
from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.runs.coding_worker import execute_coding_run


def _capture_events():
    events: list = []

    def capture(run_id, event_type, payload):
        events.append((run_id, event_type, payload))
        return len(events)

    return events, capture


def test_sanitize_redacts_secrets_and_truncates():
    payload = {
        "command": "x" * 5000,
        "api_key": "sk-live-secret",
        "nested": {"authorization": "Bearer abc"},
    }
    out = acp_updates.sanitize(payload)
    assert out["api_key"] == acp_updates.REDACTED
    assert out["nested"]["authorization"] == acp_updates.REDACTED
    assert "truncated" in out["command"]
    assert len(out["command"]) < 5000


def test_streamer_maps_message_and_thought_separately():
    events, capture = _capture_events()
    streamer = acp_updates.AcpUpdateStreamer(
        run_id="run1", phase="initial", phase_turn=1, attempt=1
    )
    with patch.object(acp_updates.store, "append_run_event", side_effect=capture):
        streamer.handle(
            {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Hel"}}}
        )
        streamer.handle(
            {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "lo"}}}
        )
        streamer.handle(
            {"update": {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "think"}}}
        )
        streamer.flush()

    by_type: dict = {}
    for _, event_type, payload in events:
        by_type.setdefault(event_type, []).append(payload)

    assert "".join(p["delta"] for p in by_type["text_append"]) == "Hello"
    assert "".join(p["delta"] for p in by_type["acp_thought_append"]) == "think"
    # Thought text never lands in the assistant text stream.
    assert all("think" not in p["delta"] for p in by_type["text_append"])


def test_streamer_maps_tool_call_and_plan_and_ignores_usage():
    events, capture = _capture_events()
    streamer = acp_updates.AcpUpdateStreamer(run_id="run1")
    with patch.object(acp_updates.store, "append_run_event", side_effect=capture):
        streamer.handle(
            {
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "c1",
                    "title": "bash",
                    "kind": "execute",
                    "status": "pending",
                    "rawInput": {"command": "ls", "api_key": "secret"},
                    "locations": [{"path": "/tmp/x"}],
                }
            }
        )
        streamer.handle(
            {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "c1",
                    "title": "bash",
                    "status": "completed",
                    "content": [{"type": "content", "content": {"type": "text", "text": "out"}}],
                    "rawOutput": {"output": "out"},
                }
            }
        )
        streamer.handle(
            {"update": {"sessionUpdate": "plan", "entries": [{"content": "step1"}]}}
        )
        streamer.handle({"update": {"sessionUpdate": "usage_update", "used": 1}})

    by_type: dict = {}
    for _, event_type, payload in events:
        by_type.setdefault(event_type, []).append(payload)

    start = by_type["acp_tool_call"][0]
    assert start["tool_call_id"] == "c1"
    assert start["tool_name"] == "bash"
    assert start["status"] == "preparing"
    assert start["args"]["command"] == "ls"
    assert start["args"]["api_key"] == acp_updates.REDACTED
    assert start["locations"] == [{"path": "/tmp/x"}]

    done = by_type["acp_tool_call_update"][0]
    assert done["status"] == "succeeded"
    assert done["result"] == "out"

    assert by_type["acp_plan"][0]["entries"] == [{"content": "step1"}]
    assert "acp_usage" not in by_type
    assert all(e[1] != "acp_usage" for e in events)


def test_streamer_flat_shape_is_treated_as_message():
    events, capture = _capture_events()
    streamer = acp_updates.AcpUpdateStreamer(run_id="run1")
    with patch.object(acp_updates.store, "append_run_event", side_effect=capture):
        streamer.handle({"text": "flat"})
        streamer.flush()
    assert any(e[1] == "text_append" for e in events)
    assert "".join(p["delta"] for _, t, p in events if t == "text_append") == "flat"


def test_bound_payload_keeps_routing_keys_when_oversized():
    payload = {
        "tool_call_id": "c1",
        "phase": "initial",
        "phase_turn": 2,
        "attempt": 1,
        "args": {"command": "x" * 20000},
    }
    bounded = acp_updates._bound_payload(payload)
    assert bounded["truncated"] is True
    assert bounded["tool_call_id"] == "c1"
    assert bounded["phase_turn"] == 2


def test_acp_turn_excludes_thought_from_output():
    """agent_thought_chunk never contributes to the worker output text."""
    profile = acp.AcpLaunchProfile.get_profile("opencode")
    client = acp.AcpClientBackend(profile)

    updates = [
        {"method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "hello"}}}},
        {"method": "session/update", "params": {"update": {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "SECRET-THOUGHT"}}}},
        {"method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": " world"}}}},
    ]
    received: list = []

    with patch.object(acp.AcpConnection, "start"), \
         patch.object(acp.AcpConnection, "is_alive", return_value=True), \
         patch.object(acp.AcpConnection, "terminate", return_value=0), \
         patch.object(acp.AcpConnection, "notify"), \
         patch.object(
             acp.AcpClientBackend,
             "initialize",
             return_value={"protocol_version": 1, "capabilities": {}},
         ), \
         patch.object(acp.AcpConnection, "request", return_value={"sessionId": "s1"}), \
         patch.object(acp.AcpConnection, "send_request_async", return_value=5), \
         patch.object(
             acp.AcpConnection,
             "wait_for_response",
             return_value={"result": {"stopReason": "end_turn"}},
         ), \
         patch.object(acp.AcpConnection, "pop_notifications", side_effect=[list(updates), []]), \
         patch.object(acp.AcpConnection, "pop_client_requests", return_value=[]):

        res = client.execute_turn(
            repo_path="/tmp",
            prompt="hi",
            on_update_callback=lambda p: received.append(p),
        )

    assert res.output == "hello world"
    assert "SECRET-THOUGHT" not in res.output
    # The thought update is still delivered to the callback for display.
    kinds = [
        p.get("update", {}).get("sessionUpdate")
        for p in received
        if isinstance(p.get("update"), dict)
    ]
    assert "agent_thought_chunk" in kinds


def test_worker_persists_acp_live_updates(tmp_path):
    repo = tmp_path / "acp_live_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    conn = get_db_connection()
    now = "2026-09-15T00:00:00+09:00"
    cur = conn.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status, created_at, updated_at, project_path) "
        "VALUES ('acp-live-proj', 'ACP Live Proj', 'personal', 'active', ?, ?, ?)",
        (now, now, str(repo)),
    )
    project_id = cur.lastrowid
    conn.commit()
    conn.close()

    sess = store.create_session(
        project_id=project_id,
        backend="opencode",
        repo_path=str(repo),
        title="ACP Live Session",
        transport="acp",
    )
    _, run = store.start_queued_run(sess["session_id"], "do ACP live work")

    async def fake_events(*args, **kwargs):
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            yield {"type": "text", "content": "<final_report>done</final_report>"}
        else:
            yield {
                "type": "text",
                "content": "go\n<cli_request>\ninspect repo\n</cli_request>",
            }

    fake_res = acp.AcpExecutionResult(
        acp_session_id="acp_live_sess",
        output="final answer",
        exit_code=0,
        stop_reason="end_turn",
        diagnostics={"acp_version": "1.0"},
    )

    def fake_execute_turn(**kwargs):
        callback = kwargs.get("on_update_callback")
        if callback is not None:
            callback({"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "live text"}}})
            callback({"update": {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "reasoning"}}})
            callback({"update": {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "bash", "status": "in_progress"}})
        return fake_res

    with (
        patch.object(CodingOrchestrator, "generate_response_events", side_effect=fake_events),
        patch.object(acp.AcpClientBackend, "execute_turn", side_effect=fake_execute_turn),
    ):
        asyncio.run(execute_coding_run(run["run_id"]))

    events = store.list_run_events(run["run_id"], 0, 500)
    types = [e["event_type"] for e in events]
    assert "text_append" in types
    assert "acp_thought_append" in types
    assert "acp_tool_call" in types

    text_deltas = [e["payload"]["delta"] for e in events if e["event_type"] == "text_append"]
    assert "".join(text_deltas) == "live text"
    assert all("reasoning" not in d for d in text_deltas)
