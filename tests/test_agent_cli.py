"""Tests for AI Agent Chat CLI (--agent-chat)."""

from __future__ import annotations

import json
import sys
from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest

from obsidian_ai_hub.agents import cli, store


@pytest.fixture
def test_agent(test_memory_db_path):
    agent = store.create_agent(
        name="Test Assistant",
        system_prompt="You are a helpful assistant.",
    )
    return agent


def test_main_agent_chat_empty_prompt_exits(monkeypatch):
    monkeypatch.setattr(sys, "stdin", StringIO(""))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    stderr = StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit) as exc_info:
        cli.main_agent_chat(agent_id="agent_dummy", prompt="")

    assert exc_info.value.code == 1
    assert "Agent prompt is empty" in stderr.getvalue()


def test_main_agent_chat_nonexistent_agent_exits(test_memory_db_path, monkeypatch):
    stderr = StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit) as exc_info:
        cli.main_agent_chat(agent_id="nonexistent_agent", prompt="Hello")

    assert exc_info.value.code == 1
    assert "Agent 'nonexistent_agent' not found" in stderr.getvalue()


def test_main_agent_chat_stdin_fallback(test_agent, monkeypatch):
    monkeypatch.setattr(sys, "stdin", StringIO("  Hello from stdin  \n"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    async def mock_stream(*args, **kwargs):
        session = kwargs.get("session") or args[1]
        run = kwargs.get("run") or args[2]
        yield f'data: {{"type": "text", "delta": "Hello from agent!"}}\n\n'
        done_payload = {
            "type": "done",
            "message": {"message_id": "amsg_1", "role": "assistant", "content": "Hello from agent!"},
            "run": run,
            "hitl_run_ids": [],
            "tool_calls": [],
        }
        yield f'data: {json.dumps(done_payload)}\n\n'

    with patch("obsidian_ai_hub.agents.runtime.generate_agent_stream", side_effect=mock_stream):
        cli.main_agent_chat(agent_id=test_agent["agent_id"], prompt=None)

    assert "Hello from agent!" in stdout.getvalue()
    assert "[session] session_id=" in stderr.getvalue()


def test_main_agent_chat_resume_session_validation(test_agent, test_memory_db_path, monkeypatch):
    # 1. Nonexistent resume session
    stderr = StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit) as exc_info:
        cli.main_agent_chat(
            agent_id=test_agent["agent_id"],
            prompt="Hello",
            resume_session="nonexistent_session",
        )

    assert exc_info.value.code == 1
    assert "Session 'nonexistent_session' not found" in stderr.getvalue()

    # 2. Resume session belonging to another agent
    other_agent = store.create_agent(name="Other Agent", system_prompt="Other")
    other_session = store.create_session(other_agent["agent_id"])

    stderr = StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit) as exc_info:
        cli.main_agent_chat(
            agent_id=test_agent["agent_id"],
            prompt="Hello",
            resume_session=other_session["session_id"],
        )

    assert exc_info.value.code == 1
    assert "belongs to agent" in stderr.getvalue()


def test_main_agent_chat_json_output(test_agent, monkeypatch):
    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    async def mock_stream(*args, **kwargs):
        run = kwargs.get("run") or args[2]
        done_payload = {
            "type": "done",
            "message": {"message_id": "amsg_2", "role": "assistant", "content": "JSON response"},
            "run": run,
            "hitl_run_ids": ["hitl_123"],
            "tool_calls": [{"id": "call_1", "tool_name": "web_search"}],
        }
        yield f'data: {json.dumps(done_payload)}\n\n'

    with patch("obsidian_ai_hub.agents.runtime.generate_agent_stream", side_effect=mock_stream):
        cli.main_agent_chat(
            agent_id=test_agent["agent_id"],
            prompt="Test JSON",
            output_format="json",
        )

    # In JSON mode, stderr progress is suppressed
    assert stderr.getvalue() == ""

    out_json = json.loads(stdout.getvalue())
    assert "session" in out_json
    assert out_json["session"]["agent_id"] == test_agent["agent_id"]
    assert out_json["message"]["content"] == "JSON response"
    assert out_json["hitl_run_ids"] == ["hitl_123"]
    assert len(out_json["tool_calls"]) == 1


def test_main_agent_chat_error_event_exits_nonzero(test_agent, monkeypatch):
    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    async def mock_stream(*args, **kwargs):
        yield f'data: {{"type": "error", "error": "LLM failed", "run_id": "arun_123"}}\n\n'

    with patch("obsidian_ai_hub.agents.runtime.generate_agent_stream", side_effect=mock_stream):
        with pytest.raises(SystemExit) as exc_info:
            cli.main_agent_chat(agent_id=test_agent["agent_id"], prompt="Fail test")

    assert exc_info.value.code == 1
    assert "[error] LLM failed" in stderr.getvalue()
