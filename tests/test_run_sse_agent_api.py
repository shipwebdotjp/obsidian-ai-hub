"""API tests for agent reconnectable runs (plan steps 3 + acceptance)."""

import asyncio
import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.runs.agent_worker import execute_agent_run
from obsidian_ai_hub.web.app import create_app


def _client(api_token):
    return TestClient(create_app(host="127.0.0.1", port=0, token=api_token))


def _make_agent_session(client, headers):
    agent_id = client.post(
        "/api/v1/agents",
        json={"name": "SSE Agent", "system_prompt": "P"},
        headers=headers,
    ).json()["agent"]["agent_id"]
    session_id = client.post(
        f"/api/v1/agents/{agent_id}/sessions", json={}, headers=headers
    ).json()["session"]["session_id"]
    return agent_id, session_id


def _sse_payloads(text: str):
    out = []
    cur_id = None
    for line in text.splitlines():
        if line.startswith("id:"):
            cur_id = int(line[len("id:"):].strip())
        elif line.startswith("data:"):
            assert cur_id is not None
            out.append((cur_id, json.loads(line[len("data:"):].strip())))
    return out


def test_agent_run_start_replay_cancel(api_token):
    client = _client(api_token)
    headers = {"Authorization": f"Bearer {api_token}"}
    _, session_id = _make_agent_session(client, headers)

    # Start run -> 202.
    res = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={"content": "hello"},
        headers={**headers, "Idempotency-Key": "key-1"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]
    assert res.json()["run"]["status"] == "queued"

    # Same key + same body replays same run (no double execution).
    res2 = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={"content": "hello"},
        headers={**headers, "Idempotency-Key": "key-1"},
    )
    assert res2.status_code == 202
    assert res2.json()["run"]["run_id"] == run_id
    assert len(agent_store.list_runs(session_id)) == 1

    # Same key + different body -> 409.
    res3 = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={"content": "different"},
        headers={**headers, "Idempotency-Key": "key-1"},
    )
    assert res3.status_code == 409

    # Active run guard: second start without key rejected.
    res4 = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={"content": "second"},
        headers=headers,
    )
    assert res4.status_code == 409

    # Execute via worker with mocked LLM (two text deltas).
    mock_llm = MagicMock()

    async def astream(_messages):
        yield AIMessageChunk(content="Hello")
        yield AIMessageChunk(content=" world")

    mock_llm.astream.side_effect = astream
    mock_llm.bind_tools.return_value = mock_llm
    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        asyncio.run(execute_agent_run(run_id))

    run = agent_store.get_run(run_id)
    assert run["status"] == "succeeded"

    # Full replay from 0 in ascending order.
    sub = client.get(f"/api/v1/agent-runs/{run_id}/events", headers=headers)
    assert sub.status_code == 200
    payloads = _sse_payloads(sub.text)
    assert len(payloads) >= 2
    ids = [eid for eid, _ in payloads]
    assert ids == sorted(ids)
    # text_append deltas concatenate to full text without duplication.
    deltas = [
        p.get("delta", "")
        for _, p in payloads
        if p.get("type") == "text_append"
    ]
    assert "".join(deltas) == "Hello world"
    assert payloads[-1][1].get("type") == "done"

    # Resume from Last-Event-ID returns only newer IDs.
    first_id = payloads[0][0]
    sub2 = client.get(
        f"/api/v1/agent-runs/{run_id}/events",
        headers={**headers, "Last-Event-ID": str(first_id)},
    )
    assert sub2.status_code == 200
    payloads2 = _sse_payloads(sub2.text)
    assert all(eid > first_id for eid, _ in payloads2)
    assert len(payloads2) == len(payloads) - 1


def test_agent_cancel_requests_cancelling(api_token):
    client = _client(api_token)
    headers = {"Authorization": f"Bearer {api_token}"}
    _, session_id = _make_agent_session(client, headers)
    run_id = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={"content": "to cancel"},
        headers=headers,
    ).json()["run"]["run_id"]

    res = client.post(f"/api/v1/agent-runs/{run_id}/cancel", headers=headers)
    assert res.status_code == 200
    assert res.json()["run"]["status"] == "cancelling"
    # Terminal cancel is idempotent.
    res2 = client.post(f"/api/v1/agent-runs/{run_id}/cancel", headers=headers)
    assert res2.status_code == 200


def test_agent_subscriber_disconnect_does_not_cancel_run(api_token):
    """SSE disconnect must not mutate the run (plan acceptance)."""
    client = _client(api_token)
    headers = {"Authorization": f"Bearer {api_token}"}
    _, session_id = _make_agent_session(client, headers)
    run_id = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={"content": "disconnect test"},
        headers=headers,
    ).json()["run"]["run_id"]

    mock_llm = MagicMock()

    async def astream(_messages):
        yield AIMessageChunk(content="still running")

    mock_llm.astream.side_effect = astream
    mock_llm.bind_tools.return_value = mock_llm
    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        asyncio.run(execute_agent_run(run_id))

    before = agent_store.get_run(run_id)["status"]
    assert before == "succeeded"
    # Full replay closes on terminal event; reading it must not change status.
    sub = client.get(f"/api/v1/agent-runs/{run_id}/events", headers=headers)
    assert sub.status_code == 200
    after = agent_store.get_run(run_id)["status"]
    assert before == after == "succeeded"


def test_agent_delete_session_refused_while_active(api_token):
    client = _client(api_token)
    headers = {"Authorization": f"Bearer {api_token}"}
    _, session_id = _make_agent_session(client, headers)
    client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={"content": "active"},
        headers=headers,
    )
    res = client.delete(f"/api/v1/agent-sessions/{session_id}", headers=headers)
    assert res.status_code == 409
