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


def test_stream_message_with_images_persists_attachments(client, auth_headers):
    import base64

    agent_res = client.post(
        "/api/v1/agents",
        json={"name": "Image Stream Agent", "system_prompt": "Prompt"},
        headers=auth_headers,
    )
    agent_id = agent_res.json()["agent"]["agent_id"]

    sess_res = client.post(
        f"/api/v1/agents/{agent_id}/sessions",
        json={},
        headers=auth_headers,
    )
    session_id = sess_res.json()["session"]["session_id"]

    image_b64 = base64.b64decode(
        # 1x1 transparent PNG
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVQYV2NgAAIAAAUAAen63NgAAAAASUVORK5CYII="
    )
    encoded = base64.b64encode(image_b64).decode("ascii")

    mock_llm = MagicMock()

    async def astream(messages):
        # Confirm a multimodal HumanMessage is fed to the model
        assert len(messages) >= 2
        user_msg = messages[-1]
        assert isinstance(user_msg.content, list)
        types = [item.get("type") for item in user_msg.content]
        assert "image_url" in types
        yield AIMessageChunk(content="画像を確認しました")

    mock_llm.astream.side_effect = astream
    mock_llm.bind_tools.return_value = mock_llm

    payload = {
        "content": "この画像は?",
        "images": [
            {"name": "pixel.png", "mime_type": "image/png", "data": encoded},
        ],
    }

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        res = client.post(
            f"/api/v1/agent-sessions/{session_id}/messages/stream",
            json=payload,
            headers=auth_headers,
        )
        assert res.status_code == 200

    detail = client.get(
        f"/api/v1/agent-sessions/{session_id}", headers=auth_headers
    ).json()
    assert len(detail["messages"]) == 2
    user_message = next(m for m in detail["messages"] if m["role"] == "user")
    assert user_message["content"] == "この画像は?"
    assert len(user_message["attachments"]) == 1
    assert user_message["attachments"][0]["name"] == "pixel.png"
    assert user_message["attachments"][0]["mime_type"] == "image/png"
    assert user_message["attachments"][0]["data"] == encoded


def test_stream_message_rejects_non_image_mime(client, auth_headers):
    agent_res = client.post(
        "/api/v1/agents",
        json={"name": "Bad Mime Agent", "system_prompt": "Prompt"},
        headers=auth_headers,
    )
    agent_id = agent_res.json()["agent"]["agent_id"]
    sess_res = client.post(
        f"/api/v1/agents/{agent_id}/sessions",
        json={},
        headers=auth_headers,
    )
    session_id = sess_res.json()["session"]["session_id"]

    res = client.post(
        f"/api/v1/agent-sessions/{session_id}/messages/stream",
        json={
            "content": "ファイルを送ります",
            "images": [
                {"name": "doc.pdf", "mime_type": "application/pdf", "data": "AAAA"},
            ],
        },
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "image/*" in res.json()["detail"]


def test_stream_message_rejects_too_many_images(client, auth_headers):
    agent_res = client.post(
        "/api/v1/agents",
        json={"name": "Too Many Images Agent", "system_prompt": "Prompt"},
        headers=auth_headers,
    )
    agent_id = agent_res.json()["agent"]["agent_id"]
    sess_res = client.post(
        f"/api/v1/agents/{agent_id}/sessions",
        json={},
        headers=auth_headers,
    )
    session_id = sess_res.json()["session"]["session_id"]

    images = [
        {"name": f"img{i}.png", "mime_type": "image/png", "data": "AAAA"}
        for i in range(6)
    ]
    res = client.post(
        f"/api/v1/agent-sessions/{session_id}/messages/stream",
        json={"content": "まとめて", "images": images},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "5" in res.json()["detail"]


def test_stream_message_rejects_invalid_base64(client, auth_headers):
    agent_res = client.post(
        "/api/v1/agents",
        json={"name": "Bad B64 Agent", "system_prompt": "Prompt"},
        headers=auth_headers,
    )
    agent_id = agent_res.json()["agent"]["agent_id"]
    sess_res = client.post(
        f"/api/v1/agents/{agent_id}/sessions",
        json={},
        headers=auth_headers,
    )
    session_id = sess_res.json()["session"]["session_id"]

    res = client.post(
        f"/api/v1/agent-sessions/{session_id}/messages/stream",
        json={
            "content": "壊れた画像",
            "images": [
                {"name": "bad.png", "mime_type": "image/png", "data": "!!!not-base64!!!"},
            ],
        },
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "base64" in res.json()["detail"].lower()


def test_stream_message_with_only_images_is_allowed(client, auth_headers):
    """An image-only message (empty user text + images) must succeed and
    persist the attachment, instead of 400'ing the request."""
    import base64

    agent_res = client.post(
        "/api/v1/agents",
        json={"name": "Image-Only Agent", "system_prompt": "Prompt"},
        headers=auth_headers,
    )
    agent_id = agent_res.json()["agent"]["agent_id"]
    sess_res = client.post(
        f"/api/v1/agents/{agent_id}/sessions",
        json={},
        headers=auth_headers,
    )
    session_id = sess_res.json()["session"]["session_id"]

    image_b64 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVQYV2NgAAIAAAUAAen63NgAAAAASUVORK5CYII="
    )
    encoded = base64.b64encode(image_b64).decode("ascii")

    mock_llm = MagicMock()

    async def astream(messages):
        yield AIMessageChunk(content="了解しました")

    mock_llm.astream.side_effect = astream
    mock_llm.bind_tools.return_value = mock_llm

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        res = client.post(
            f"/api/v1/agent-sessions/{session_id}/messages/stream",
            json={
                "content": "",
                "images": [
                    {"name": "pixel.png", "mime_type": "image/png", "data": encoded},
                ],
            },
            headers=auth_headers,
        )
        assert res.status_code == 200

    detail = client.get(
        f"/api/v1/agent-sessions/{session_id}", headers=auth_headers
    ).json()
    assert len(detail["messages"]) == 2
    user_message = next(m for m in detail["messages"] if m["role"] == "user")
    assert user_message["content"] == ""
    assert len(user_message["attachments"]) == 1


def test_stream_message_rejects_fully_empty_payload(client, auth_headers):
    agent_res = client.post(
        "/api/v1/agents",
        json={"name": "Empty Empty Agent", "system_prompt": "Prompt"},
        headers=auth_headers,
    )
    agent_id = agent_res.json()["agent"]["agent_id"]
    sess_res = client.post(
        f"/api/v1/agents/{agent_id}/sessions",
        json={},
        headers=auth_headers,
    )
    session_id = sess_res.json()["session"]["session_id"]

    res = client.post(
        f"/api/v1/agent-sessions/{session_id}/messages/stream",
        json={"content": "   ", "images": []},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()
