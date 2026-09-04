import pytest
from fastapi.testclient import TestClient

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

    res = client.get("/api/v1/agent-sessions/search?q=test")
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


def test_search_agent_messages_across_agents(client, auth_headers):
    from obsidian_ai_hub.agents import store

    first_agent = client.post(
        "/api/v1/agents",
        json={"name": "Search API First", "system_prompt": "Prompt"},
        headers=auth_headers,
    ).json()["agent"]
    second_agent = client.post(
        "/api/v1/agents",
        json={"name": "Search API Second", "system_prompt": "Prompt"},
        headers=auth_headers,
    ).json()["agent"]
    first_session = client.post(
        f"/api/v1/agents/{first_agent['agent_id']}/sessions",
        json={"title": "第一会話"},
        headers=auth_headers,
    ).json()["session"]
    second_session = client.post(
        f"/api/v1/agents/{second_agent['agent_id']}/sessions",
        json={"title": "第二会話"},
        headers=auth_headers,
    ).json()["session"]
    first_message, _ = store.start_user_run(first_session["session_id"], "共通の検索語")
    second_message, _ = store.start_user_run(second_session["session_id"], "共通の検索語です")

    res = client.get("/api/v1/agent-sessions/search?q=%E5%85%B1%E9%80%9A", headers=auth_headers)

    assert res.status_code == 200
    results = res.json()["results"]
    assert {item["message_id"] for item in results} == {
        first_message["message_id"],
        second_message["message_id"],
    }
    assert {item["agent_name"] for item in results} == {
        "Search API First",
        "Search API Second",
    }

    blank = client.get("/api/v1/agent-sessions/search?q=%20%20", headers=auth_headers)
    assert blank.status_code == 400


def _make_run_session(client, auth_headers, name="Run Agent"):
    agent_id = client.post(
        "/api/v1/agents",
        json={"name": name, "system_prompt": "Prompt"},
        headers=auth_headers,
    ).json()["agent"]["agent_id"]
    session_id = client.post(
        f"/api/v1/agents/{agent_id}/sessions", json={}, headers=auth_headers
    ).json()["session"]["session_id"]
    return session_id


def test_start_run_errors(client, auth_headers):
    res = client.post(
        "/api/v1/agent-sessions/non_existent_session/runs",
        json={"content": "hi"},
        headers=auth_headers,
    )
    assert res.status_code == 404

    session_id = _make_run_session(client, auth_headers, "Empty Run Agent")
    res_empty = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={"content": "   "},
        headers=auth_headers,
    )
    assert res_empty.status_code == 400


def test_start_run_with_images_persists_attachments(client, auth_headers):
    import base64

    session_id = _make_run_session(client, auth_headers, "Image Run Agent")
    image_b64 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVQYV2NgAAIAAAUAAen63NgAAAAASUVORK5CYII="
    )
    encoded = base64.b64encode(image_b64).decode("ascii")
    res = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={
            "content": "この画像は?",
            "images": [{"name": "pixel.png", "mime_type": "image/png", "data": encoded}],
        },
        headers=auth_headers,
    )
    assert res.status_code == 202
    detail = client.get(
        f"/api/v1/agent-sessions/{session_id}", headers=auth_headers
    ).json()
    # Queued run already persisted the user message with attachments.
    assert len(detail["messages"]) == 1
    assert detail["messages"][0]["attachments"][0]["name"] == "pixel.png"


def test_start_run_rejects_non_image_mime(client, auth_headers):
    session_id = _make_run_session(client, auth_headers, "Bad Mime Run Agent")
    res = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={
            "content": "ファイルを送ります",
            "images": [{"name": "doc.pdf", "mime_type": "application/pdf", "data": "AAAA"}],
        },
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "image/*" in res.json()["detail"]


def test_start_run_rejects_too_many_images(client, auth_headers):
    session_id = _make_run_session(client, auth_headers, "Too Many Run Agent")
    images = [
        {"name": f"img{i}.png", "mime_type": "image/png", "data": "AAAA"} for i in range(6)
    ]
    res = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={"content": "まとめて", "images": images},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "5" in res.json()["detail"]


def test_start_run_rejects_invalid_base64(client, auth_headers):
    session_id = _make_run_session(client, auth_headers, "Bad B64 Run Agent")
    res = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={
            "content": "壊れた画像",
            "images": [{"name": "bad.png", "mime_type": "image/png", "data": "!!!not-base64!!!"}],
        },
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "base64" in res.json()["detail"].lower()


def test_start_run_with_only_images_is_allowed(client, auth_headers):
    import base64

    session_id = _make_run_session(client, auth_headers, "Image-Only Run Agent")
    image_b64 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVQYV2NgAAIAAAUAAen63NgAAAAASUVORK5CYII="
    )
    encoded = base64.b64encode(image_b64).decode("ascii")
    res = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={
            "content": "",
            "images": [{"name": "pixel.png", "mime_type": "image/png", "data": encoded}],
        },
        headers=auth_headers,
    )
    assert res.status_code == 202


def test_start_run_rejects_fully_empty_payload(client, auth_headers):
    session_id = _make_run_session(client, auth_headers, "Empty Empty Run Agent")
    res = client.post(
        f"/api/v1/agent-sessions/{session_id}/runs",
        json={"content": "   ", "images": []},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()
