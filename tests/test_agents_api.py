import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def auth_headers(api_token):
    return {"Authorization": f"Bearer {api_token}"}


@pytest.fixture
def client(api_token):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app)


def test_agent_endpoints_require_auth(client):
    res = client.get("/api/v1/agents")
    assert res.status_code == 401

    res = client.get("/api/v1/agent-tools")
    assert res.status_code == 401


def test_list_agent_tools(client, auth_headers):
    res = client.get("/api/v1/agent-tools", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    tools = data["tools"]
    tool_ids = [t["tool_id"] for t in tools]
    assert "web_search" in tool_ids
    assert "calendar_create_proposal" in tool_ids


def test_agent_crud_flow(client, auth_headers):
    # 1. Create agent
    payload = {
        "name": "API Assistant",
        "system_prompt": "Prompt text",
        "tool_ids": ["web_search", "calendar_read"],
        "provider": "openai",
        "model": "gpt-4o",
    }
    res = client.post("/api/v1/agents", json=payload, headers=auth_headers)
    assert res.status_code == 201
    agent = res.json()["agent"]
    agent_id = agent["agent_id"]
    assert agent["name"] == "API Assistant"

    # 2. Duplicate name error
    res = client.post("/api/v1/agents", json=payload, headers=auth_headers)
    assert res.status_code == 409

    # 3. List agents
    res = client.get("/api/v1/agents", headers=auth_headers)
    assert res.status_code == 200
    agents = res.json()["agents"]
    assert any(a["agent_id"] == agent_id for a in agents)

    # 4. Get detail
    res = client.get(f"/api/v1/agents/{agent_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["agent"]["agent_id"] == agent_id

    # 5. Patch update
    res = client.patch(
        f"/api/v1/agents/{agent_id}",
        json={"name": "Updated API Assistant", "provider": ""},
        headers=auth_headers,
    )
    assert res.status_code == 200
    updated = res.json()["agent"]
    assert updated["name"] == "Updated API Assistant"
    assert updated["provider"] is None

    # 6. Delete agent
    res = client.delete(f"/api/v1/agents/{agent_id}", headers=auth_headers)
    assert res.status_code == 200

    res = client.get(f"/api/v1/agents/{agent_id}", headers=auth_headers)
    assert res.status_code == 404


def test_session_crud_flow(client, auth_headers):
    # Create agent
    agent_res = client.post(
        "/api/v1/agents",
        json={"name": "Session Agent", "system_prompt": "Prompt"},
        headers=auth_headers,
    )
    agent_id = agent_res.json()["agent"]["agent_id"]

    # Create session
    sess_res = client.post(
        f"/api/v1/agents/{agent_id}/sessions",
        json={"title": "Session Title"},
        headers=auth_headers,
    )
    assert sess_res.status_code == 201
    session_id = sess_res.json()["session"]["session_id"]

    # List sessions
    list_res = client.get(f"/api/v1/agents/{agent_id}/sessions", headers=auth_headers)
    assert list_res.status_code == 200
    sessions = list_res.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id

    # Get session detail
    detail_res = client.get(f"/api/v1/agent-sessions/{session_id}", headers=auth_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["session"]["session_id"] == session_id
    assert detail["agent"]["agent_id"] == agent_id
    assert detail["messages"] == []
    assert detail["runs"] == []

    # Delete session
    del_res = client.delete(f"/api/v1/agent-sessions/{session_id}", headers=auth_headers)
    assert del_res.status_code == 200

    res = client.get(f"/api/v1/agent-sessions/{session_id}", headers=auth_headers)
    assert res.status_code == 404


def test_stream_message_sse_api(client, auth_headers):
    agent_res = client.post(
        "/api/v1/agents",
        json={"name": "Stream Agent API", "system_prompt": "Prompt"},
        headers=auth_headers,
    )
    agent_id = agent_res.json()["agent"]["agent_id"]

    sess_res = client.post(
        f"/api/v1/agents/{agent_id}/sessions",
        json={},
        headers=auth_headers,
    )
    session_id = sess_res.json()["session"]["session_id"]

    mock_llm = MagicMock()

    async def astream(_messages):
        yield AIMessageChunk(content="APIからの")
        yield AIMessageChunk(content="応答テスト")

    mock_llm.astream.side_effect = astream
    mock_llm.bind_tools.return_value = mock_llm

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        res = client.post(
            f"/api/v1/agent-sessions/{session_id}/messages/stream",
            json={"content": "テスト発話"},
            headers=auth_headers,
        )
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in res.text.splitlines()
            if line.startswith("data: ")
        ]
        assert [payload["type"] for payload in payloads] == [
            "thinking",
            "text",
            "text",
            "done",
        ]
        assert (
            "".join(
                payload["delta"] for payload in payloads if payload["type"] == "text"
            )
            == "APIからの応答テスト"
        )
        assert payloads[-1]["message"]["content"] == "APIからの応答テスト"


def test_stream_message_errors(client, auth_headers):
    # Non-existent session -> 404
    res = client.post(
        "/api/v1/agent-sessions/non_existent_session/messages/stream",
        json={"content": "テスト発話"},
        headers=auth_headers,
    )
    assert res.status_code == 404

    # Empty content -> 400
    agent_res = client.post(
        "/api/v1/agents",
        json={"name": "Empty Stream Agent", "system_prompt": "Prompt"},
        headers=auth_headers,
    )
    agent_id = agent_res.json()["agent"]["agent_id"]

    sess_res = client.post(
        f"/api/v1/agents/{agent_id}/sessions",
        json={},
        headers=auth_headers,
    )
    session_id = sess_res.json()["session"]["session_id"]

    res_empty = client.post(
        f"/api/v1/agent-sessions/{session_id}/messages/stream",
        json={"content": "   "},
        headers=auth_headers,
    )
    assert res_empty.status_code == 400
