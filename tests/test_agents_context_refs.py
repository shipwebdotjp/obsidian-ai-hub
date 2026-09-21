"""Vault context references (the agent ``@`` picker): listing, intake, storage."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from obsidian_ai_hub.agents import runtime, store, vault_context
from obsidian_ai_hub.utils import config
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def auth_headers(api_token):
    return {"Authorization": f"Bearer {api_token}"}


@pytest.fixture
def client(api_token):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app)


@pytest.fixture
def vault_dir(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note-a.md").write_text("# A\n本文A\n", encoding="utf-8")
    (vault / "sub").mkdir()
    (vault / "sub" / "note-b.md").write_text("# B\n本文B\n", encoding="utf-8")
    (vault / "ignore.txt").write_text("not markdown", encoding="utf-8")
    hidden = vault / ".obsidian"
    hidden.mkdir()
    (hidden / "hidden.md").write_text("hidden", encoding="utf-8")
    monkeypatch.setattr(config, "VAULT_PATH", vault)
    return vault


def test_normalize_context_refs_filters_and_dedupes():
    refs = vault_context.normalize_context_refs(
        [
            {"kind": "vault_file", "path": "a.md"},
            {"kind": "vault_file", "path": " a.md "},
            {"kind": "other", "path": "a.md"},
            {"kind": "vault_file", "path": ""},
            "not-a-dict",
            None,
            {"kind": "vault_file", "path": "b.md"},
        ]
    )
    assert refs == [
        {"kind": "vault_file", "path": "a.md"},
        {"kind": "vault_file", "path": "b.md"},
    ]


def test_normalize_context_refs_caps_at_limit():
    refs = vault_context.normalize_context_refs(
        [{"kind": "vault_file", "path": f"{i}.md"} for i in range(10)]
    )
    assert len(refs) == vault_context.MAX_AGENT_CONTEXT_REFS


def test_build_context_block_reads_live_content(vault_dir):
    block = vault_context.build_context_block(
        [{"kind": "vault_file", "path": "note-a.md"}]
    )
    assert "note-a.md" in block
    assert "本文A" in block

    # Re-read: edits between turns are reflected.
    (vault_dir / "note-a.md").write_text("# A\n更新後\n", encoding="utf-8")
    block = vault_context.build_context_block(
        [{"kind": "vault_file", "path": "note-a.md"}]
    )
    assert "更新後" in block
    assert "本文A" not in block


def test_build_context_block_missing_file_does_not_raise(vault_dir):
    block = vault_context.build_context_block(
        [
            {"kind": "vault_file", "path": "note-a.md"},
            {"kind": "vault_file", "path": "gone.md"},
        ]
    )
    assert "本文A" in block
    assert "gone.md" in block


def test_compose_user_text_orders_context_before_instruction(vault_dir):
    composed = vault_context.compose_user_text(
        "要約して", [{"kind": "vault_file", "path": "note-a.md"}]
    )
    assert composed.index("本文A") < composed.index("要約して")


def test_compose_user_text_without_refs_is_passthrough():
    assert vault_context.compose_user_text("hi", None) == "hi"
    assert vault_context.compose_user_text("hi", []) == "hi"


def test_store_persists_context_refs_on_queued_run():
    agent = store.create_agent(name="Refs Agent", system_prompt="x")
    session = store.create_session(agent["agent_id"])
    refs = [{"kind": "vault_file", "path": "note-a.md"}]
    msg, run = store.start_queued_run(
        session["session_id"], "見て", context_refs=refs
    )
    assert msg["context_refs"] == refs
    fetched = store.get_message(msg["message_id"])
    assert fetched is not None
    assert fetched["context_refs"] == refs
    listed = store.list_messages(session["session_id"])
    assert listed[0]["context_refs"] == refs


def test_store_allows_empty_content_with_refs_only():
    agent = store.create_agent(name="Refs Only Agent", system_prompt="x")
    session = store.create_session(agent["agent_id"])
    msg, _ = store.start_queued_run(
        session["session_id"], "   ", context_refs=[{"kind": "vault_file", "path": "a.md"}]
    )
    assert msg["content"] == ""
    assert msg["context_refs"] == [{"kind": "vault_file", "path": "a.md"}]


def test_store_idempotency_hash_covers_refs():
    agent = store.create_agent(name="Refs Idem Agent", system_prompt="x")
    session = store.create_session(agent["agent_id"])
    key = "idem-refs-1"
    _, first = store.start_queued_run(
        session["session_id"],
        "text",
        idempotency_key=key,
        context_refs=[{"kind": "vault_file", "path": "a.md"}],
    )
    # Same key + same body replays the first run.
    _, replay = store.start_queued_run(
        session["session_id"],
        "text",
        idempotency_key=key,
        context_refs=[{"kind": "vault_file", "path": "a.md"}],
    )
    assert replay["run_id"] == first["run_id"]
    # Same key + different refs conflicts.
    with pytest.raises(ValueError, match="conflict"):
        store.start_queued_run(
            session["session_id"],
            "text",
            idempotency_key=key,
            context_refs=[{"kind": "vault_file", "path": "b.md"}],
        )


def _create_agent_and_session(client, headers):
    agent = client.post(
        "/api/v1/agents",
        json={"name": "Refs API Agent", "system_prompt": "x"},
        headers=headers,
    ).json()["agent"]
    session = client.post(
        f"/api/v1/agents/{agent['agent_id']}/sessions",
        json={},
        headers=headers,
    ).json()["session"]
    return session


def test_vault_files_requires_auth(client):
    res = client.get("/api/v1/vault-files")
    assert res.status_code == 401


def test_vault_files_lists_markdown_only(client, auth_headers, vault_dir):
    res = client.get("/api/v1/vault-files", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    paths = [item["relative_path"] for item in body["items"]]
    assert "note-a.md" in paths
    assert "sub/note-b.md" in paths
    assert "ignore.txt" not in paths
    assert ".obsidian/hidden.md" not in paths
    assert body["total"] == len(paths)
    item = next(i for i in body["items"] if i["relative_path"] == "note-a.md")
    assert item["size"] > 0
    assert item["mtime"] > 0


def test_vault_files_excludes_symlink_escape(client, auth_headers, vault_dir, tmp_path):
    import os

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    os.symlink(outside, vault_dir / "link")
    os.symlink(
        vault_dir / "note-a.md", vault_dir / "sub" / "note-a-link.md"
    )
    res = client.get("/api/v1/vault-files", headers=auth_headers)
    assert res.status_code == 200
    paths = [item["relative_path"] for item in res.json()["items"]]
    assert "link/secret.md" not in paths
    assert "sub/note-a-link.md" in paths


def test_start_run_accepts_context_refs(client, auth_headers, vault_dir):
    session = _create_agent_and_session(client, auth_headers)
    res = client.post(
        f"/api/v1/agent-sessions/{session['session_id']}/runs",
        json={
            "content": "このノートを見て",
            "context_refs": [{"kind": "vault_file", "path": "note-a.md"}],
        },
        headers=auth_headers,
    )
    assert res.status_code == 202
    detail = client.get(
        f"/api/v1/agent-sessions/{session['session_id']}", headers=auth_headers
    ).json()
    user_message = next(m for m in detail["messages"] if m["role"] == "user")
    assert user_message["context_refs"] == [
        {"kind": "vault_file", "path": "note-a.md"}
    ]


def test_start_run_accepts_refs_only_message(client, auth_headers, vault_dir):
    session = _create_agent_and_session(client, auth_headers)
    res = client.post(
        f"/api/v1/agent-sessions/{session['session_id']}/runs",
        json={
            "content": "   ",
            "context_refs": [{"kind": "vault_file", "path": "sub/note-b.md"}],
        },
        headers=auth_headers,
    )
    assert res.status_code == 202


def test_start_run_rejects_too_many_refs(client, auth_headers, vault_dir):
    session = _create_agent_and_session(client, auth_headers)
    res = client.post(
        f"/api/v1/agent-sessions/{session['session_id']}/runs",
        json={
            "content": "x",
            "context_refs": [
                {"kind": "vault_file", "path": f"note-{i}.md"} for i in range(6)
            ],
        },
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_start_run_rejects_missing_file(client, auth_headers, vault_dir):
    session = _create_agent_and_session(client, auth_headers)
    res = client.post(
        f"/api/v1/agent-sessions/{session['session_id']}/runs",
        json={
            "content": "x",
            "context_refs": [{"kind": "vault_file", "path": "nope.md"}],
        },
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_start_run_rejects_non_markdown_and_traversal(
    client, auth_headers, vault_dir
):
    session = _create_agent_and_session(client, auth_headers)
    for bad in ("ignore.txt", "../outside.md", "/abs.md"):
        res = client.post(
            f"/api/v1/agent-sessions/{session['session_id']}/runs",
            json={
                "content": "x",
                "context_refs": [{"kind": "vault_file", "path": bad}],
            },
            headers=auth_headers,
        )
        assert res.status_code == 400, bad


def test_start_run_rejects_unknown_kind(client, auth_headers, vault_dir):
    session = _create_agent_and_session(client, auth_headers)
    res = client.post(
        f"/api/v1/agent-sessions/{session['session_id']}/runs",
        json={
            "content": "x",
            "context_refs": [{"kind": "project", "path": "note-a.md"}],
        },
        headers=auth_headers,
    )
    assert res.status_code == 400


@pytest.mark.anyio
async def test_agent_stream_injects_refs_for_current_and_history_messages(vault_dir):
    """Context refs on the current turn AND on a prior user turn must both
    reach the LLM as note content inside the user text."""
    agent = store.create_agent(name="Refs Runtime Agent", system_prompt="Help!")
    session = store.create_session(agent["agent_id"])

    _prior_msg, prior_run = store.start_user_run(
        session["session_id"],
        "前のノート",
        context_refs=[{"kind": "vault_file", "path": "sub/note-b.md"}],
    )
    store.complete_run(prior_run["run_id"], assistant_content="見ました。")

    captured_messages: list = []
    mock_llm = MagicMock()

    async def astream(messages):
        captured_messages.extend(messages)
        yield AIMessageChunk(content="両方見ました")

    mock_llm.astream.side_effect = astream
    mock_llm.bind_tools.return_value = mock_llm

    history = store.list_messages(session["session_id"])
    _user_msg, run = store.start_user_run(
        session["session_id"],
        "今のノート",
        context_refs=[{"kind": "vault_file", "path": "note-a.md"}],
    )

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        events = [
            event
            async for event in runtime.generate_agent_stream(
                agent=agent,
                session=session,
                run=run,
                history_messages=history,
                user_content="今のノート",
                context_refs=[{"kind": "vault_file", "path": "note-a.md"}],
            )
        ]

    payloads = [json.loads(e.removeprefix("data: ").strip()) for e in events]
    assert payloads[-1]["type"] == "done"

    human_messages = [
        m for m in captured_messages if m.__class__.__name__ == "HumanMessage"
    ]
    assert len(human_messages) == 2
    prior_text = human_messages[0].content
    current_text = human_messages[1].content
    assert isinstance(prior_text, str)
    assert isinstance(current_text, str)
    assert "本文B" in prior_text
    assert "前のノート" in prior_text
    assert "本文A" in current_text
    assert "今のノート" in current_text


@pytest.mark.anyio
async def test_agent_stream_survives_deleted_ref(vault_dir):
    """A note deleted after send degrades to a notice, not a failed run."""
    agent = store.create_agent(name="Refs Missing Agent", system_prompt="Help!")
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(
        session["session_id"],
        "見て",
        context_refs=[{"kind": "vault_file", "path": "note-a.md"}],
    )
    (vault_dir / "note-a.md").unlink()

    mock_llm = MagicMock()

    async def astream(messages):
        yield AIMessageChunk(content="ok")

    mock_llm.astream.side_effect = astream
    mock_llm.bind_tools.return_value = mock_llm

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
    ):
        events = [
            event
            async for event in runtime.generate_agent_stream(
                agent=agent,
                session=session,
                run=run,
                history_messages=[user_msg],
                user_content="見て",
                context_refs=[{"kind": "vault_file", "path": "note-a.md"}],
            )
        ]

    payloads = [json.loads(e.removeprefix("data: ").strip()) for e in events]
    assert payloads[-1]["type"] == "done"
