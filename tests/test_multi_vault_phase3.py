"""Multi-Vault Phase 3: agent defaults, trusted actors, authorization gates."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from obsidian_ai_hub.agents import registry as agent_registry
from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.agents import vault_context
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.web.services import vault as vault_service


@pytest.fixture
def none_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Registry with an ai_access=none vault alongside the standard three."""
    main_vault = tmp_path / "v" / "main"
    blog_vault = tmp_path / "v" / "blog"
    ai_vault = tmp_path / "v" / "ai"
    secret_vault = tmp_path / "v" / "secret"
    for d in (main_vault, blog_vault, ai_vault, secret_vault):
        d.mkdir(parents=True, exist_ok=True)
    registry = app_config.validate_vault_registry(
        {
            "vaults": {
                "main": {
                    "path": str(main_vault),
                    "display_name": "Personal",
                    "role": "primary",
                    "ai_access": "read",
                },
                "blog": {
                    "path": str(blog_vault),
                    "display_name": "Blog",
                    "ai_access": "write",
                },
                "ai": {
                    "path": str(ai_vault),
                    "display_name": "AI",
                    "ai_access": "write",
                },
                "secret": {
                    "path": str(secret_vault),
                    "display_name": "Secret",
                    "ai_access": "none",
                },
            }
        }
    )
    monkeypatch.setattr(app_config, "VAULT_REGISTRY", registry)
    monkeypatch.setattr(app_config, "PRIMARY_VAULT", registry.get_primary())
    return registry


# --- default_vault_ids -------------------------------------------------------


def test_create_agent_defaults_to_main(test_memory_db_path):
    agent = agent_store.create_agent(name="a1", system_prompt="p")
    assert agent["default_vault_ids"] == ["main"]


def test_create_and_update_agent_vault_ids(test_memory_db_path):
    agent = agent_store.create_agent(
        name="a2", system_prompt="p", default_vault_ids=["blog", "ai"]
    )
    assert agent["default_vault_ids"] == ["blog", "ai"]
    updated = agent_store.update_agent(
        agent["agent_id"], default_vault_ids=["ai", "blog", "ai", " "]
    )
    assert updated["default_vault_ids"] == ["ai", "blog"]
    # Other fields untouched when vault ids omitted.
    renamed = agent_store.update_agent(agent["agent_id"], name="a2b")
    assert renamed["default_vault_ids"] == ["ai", "blog"]
    assert renamed["name"] == "a2b"


def test_normalize_default_vault_ids_falls_back_to_main():
    assert agent_store._normalize_default_vault_ids(None) == ["main"]
    assert agent_store._normalize_default_vault_ids([]) == ["main"]
    assert agent_store._normalize_default_vault_ids([" ", ""]) == ["main"]
    assert agent_store._normalize_default_vault_ids("blog") == ["blog"]


def test_migration_v78_backfills_main(test_memory_db_path):
    import sqlite3

    from obsidian_ai_hub.database import get_db_connection

    init_conn = get_db_connection()
    init_conn.close()
    conn = sqlite3.connect(str(test_memory_db_path))
    conn.row_factory = sqlite3.Row
    cols = [r[1] for r in conn.execute("PRAGMA table_info(agents);").fetchall()]
    assert "default_vault_ids_json" in cols
    # Simulate a pre-migration row: default applies, history untouched.
    conn.execute(
        "INSERT INTO agents (agent_id, name, system_prompt, created_at, updated_at)"
        " VALUES ('agent_old', 'old', 'p', 't', 't');"
    )
    conn.commit()
    row = conn.execute(
        "SELECT default_vault_ids_json FROM agents WHERE agent_id = 'agent_old';"
    ).fetchone()
    assert json.loads(row[0]) == ["main"]
    conn.close()
    agent = agent_store.get_agent("agent_old")
    assert agent is not None and agent["default_vault_ids"] == ["main"]


# --- ai_access gates at the service choke point ------------------------------


def test_agent_write_to_blog_allowed_main_denied():
    ok = vault_service.write_vault_file(
        "post.md", "hello", vault_id="blog", actor="agent"
    )
    assert ok["vault_id"] == "blog"
    with pytest.raises(PermissionError):
        vault_service.write_vault_file(
            "note.md", "hello", vault_id="main", actor="agent"
        )
    with pytest.raises(PermissionError):
        vault_service.write_vault_file(
            "note.md", "hello", vault_id="main", actor="task"
        )
    with pytest.raises(PermissionError):
        vault_service.write_vault_file(
            "note.md", "hello", vault_id="main", actor="workflow"
        )


def test_read_only_vault_rejects_agent_write():
    with pytest.raises(PermissionError):
        vault_service.write_vault_file(
            "note.md", "hi", vault_id="main", actor="agent"
        )


def test_none_vault_rejects_agent_read_and_search(none_registry):
    (none_registry.get("secret").path / "s.md").write_text("shh", encoding="utf-8")
    with pytest.raises(PermissionError):
        vault_service.get_vault_file("s.md", vault_id="secret", actor="agent")
    with pytest.raises(PermissionError):
        vault_service.list_vault_files(vault_id="secret", actor="agent")
    with patch(
        "obsidian_ai_hub.web.services.vault.obsidian_vault_retriever.search_single_vault",
        return_value=json.dumps([]),
    ) as spy:
        result = vault_service.search_vault(q="x", actor="agent")
        called = {c.kwargs.get("vault_id") for c in spy.call_args_list}
        assert "secret" not in called
        assert result["total"] == 0


def test_human_and_internal_actors_unrestricted(none_registry):
    (none_registry.get("secret").path / "s.md").write_text("shh", encoding="utf-8")
    got = vault_service.get_vault_file("s.md", vault_id="secret", actor="human")
    assert got["content"] == "shh"
    res = vault_service.write_vault_file(
        "internal-note.md", "sys", vault_id="main", actor="internal"
    )
    assert res["vault_id"] == "main"
    human = vault_service.write_vault_file(
        "human-note.md", "hi", vault_id="main", actor="human"
    )
    assert human["vault_id"] == "main"


def test_unknown_actor_rejected():
    with pytest.raises(ValueError):
        vault_service.write_vault_file("x.md", "hi", vault_id="blog", actor="llm")


# --- agent tools -------------------------------------------------------------


def test_agent_search_uses_defaults_plus_additional():
    seen: dict = {}

    def fake_search(q, k=10, mode="hybrid", vault_ids=None, actor="human"):
        seen["vault_ids"] = list(vault_ids or [])
        seen["actor"] = actor
        return {"items": [], "total": 0}

    tool = agent_registry._make_vault_search_tool(
        {"actor_kind": "agent", "default_vault_ids": ["main"]}
    )
    with patch(
        "obsidian_ai_hub.web.services.vault.search_vault", side_effect=fake_search
    ):
        out = json.loads(
            tool.invoke({"query": "hello", "additional_vault_ids": ["blog"]})
        )
    assert out == []
    assert seen["vault_ids"] == ["main", "blog"]
    assert seen["actor"] == "agent"


def test_agent_search_tool_shape_kept_for_tasks():
    model = agent_registry.VaultSearchInput
    assert set(model.model_fields) >= {
        "query",
        "k",
        "search_mode",
        "additional_vault_ids",
    }
    # Task capability input validation accepts the new fields.
    from obsidian_ai_hub.tasks import capability_schemas as schemas

    validated = schemas.validate_capability_inputs(
        "vault_search", {"query": "x", "additional_vault_ids": ["blog"]}
    )
    assert validated["additional_vault_ids"] == ["blog"]


def test_bound_write_tool_denies_main_allows_blog():
    agent_tool = agent_registry._make_vault_write_tool({"actor_kind": "agent"})
    denied = json.loads(
        agent_tool.invoke({"relative_path": "n.md", "content": "x"})
    )
    assert "error" in denied
    allowed = json.loads(
        agent_tool.invoke(
            {"relative_path": "n.md", "content": "x", "vault_id": "ai"}
        )
    )
    assert allowed["vault_id"] == "ai"

    task_tool = agent_registry._make_vault_write_tool({"actor_kind": "task"})
    denied_task = json.loads(
        task_tool.invoke(
            {"relative_path": "n.md", "content": "x", "vault_id": "main"}
        )
    )
    assert "error" in denied_task


def test_task_context_actor_task_vs_workflow():
    from obsidian_ai_hub.tasks.adapters.registry_tools import _task_context

    plain = _task_context({"task_id": "t1", "prompt_text": "hi"})
    assert plain["actor_kind"] == "task"
    bridge = _task_context(
        {"task_id": "t2", "prompt_text": "", "workflow_run_id": "w1"}
    )
    assert bridge["actor_kind"] == "workflow"


def test_task_write_to_main_denied_end_to_end(test_memory_db_path):
    from obsidian_ai_hub.tasks import store as task_store
    from obsidian_ai_hub.tasks.adapters import get_default_executor

    task = task_store.create_task("write to main")
    plan = task_store.create_plan(
        task["task_id"],
        {
            "purpose": "deny",
            "steps": [
                {
                    "capability_key": "vault_write_file",
                    "title": "write main",
                    "target": {},
                    "inputs": {"relative_path": "blocked.md", "content": "x"},
                    "side_effects": "vault write",
                }
            ],
            "completion_criteria": "done",
        },
        {"vault_write_file": "plan_required"},
    )
    result = get_default_executor().execute_step(
        task, plan, 0, plan["plan"]["steps"][0]
    )
    assert "error" in result.summary
    assert not (
        app_config.PRIMARY_VAULT_PATH / "blocked.md"
    ).exists()


def test_task_write_policy_stays_plan_required():
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

    by_key = {d.key: d for d in get_capability_definitions()}
    assert by_key["vault_write_file"].default_approval_policy == "plan_required"


# --- context refs ------------------------------------------------------------


def test_context_refs_keep_vault_id_and_migrate_old():
    refs = vault_context.normalize_context_refs(
        [
            {"kind": "vault_file", "path": "a.md"},
            {"kind": "vault_file", "vault_id": "blog", "path": "b.md"},
            {"kind": "vault_file", "vault_id": "blog", "path": "b.md"},
            {"kind": "vault_file", "vault_id": " ", "path": "c.md"},
        ]
    )
    assert refs == [
        {"kind": "vault_file", "vault_id": "main", "path": "a.md"},
        {"kind": "vault_file", "vault_id": "blog", "path": "b.md"},
        {"kind": "vault_file", "vault_id": "main", "path": "c.md"},
    ]


def test_context_block_reads_other_vault():
    vault_service.write_vault_file("cross.md", "blog-body", vault_id="blog")
    block = vault_context.build_context_block(
        [{"kind": "vault_file", "vault_id": "blog", "path": "cross.md"}]
    )
    assert "blog-body" in block
    assert "[blog] cross.md" in block


def test_agent_api_vault_ids_roundtrip(api_token):
    from fastapi.testclient import TestClient

    from obsidian_ai_hub.web.app import create_app

    app = create_app(host="127.0.0.1", port=0, token=api_token)
    client = TestClient(app, headers={"Authorization": f"Bearer {api_token}"})
    res = client.post(
        "/api/v1/agents",
        json={
            "name": "vault-agent",
            "system_prompt": "p",
            "tool_ids": ["vault_search"],
            "default_vault_ids": ["blog", "ai"],
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["agent"]["default_vault_ids"] == ["blog", "ai"]
    agent_id = res.json()["agent"]["agent_id"]
    bad = client.post(
        "/api/v1/agents",
        json={
            "name": "bad-agent",
            "system_prompt": "p",
            "default_vault_ids": ["nope"],
        },
    )
    assert bad.status_code == 400
    upd = client.patch(
        f"/api/v1/agents/{agent_id}", json={"default_vault_ids": ["main"]}
    )
    assert upd.status_code == 200
    assert upd.json()["agent"]["default_vault_ids"] == ["main"]


def test_agent_create_cli_accepts_vault_ids(tmp_path, test_memory_db_path):
    from obsidian_ai_hub.agents.cli import main_agent_create

    payload = tmp_path / "agent.json"
    payload.write_text(
        json.dumps(
            {
                "name": "cli-agent",
                "system_prompt": "p",
                "default_vault_ids": ["ai"],
            }
        ),
        encoding="utf-8",
    )
    assert main_agent_create(str(payload)) == 0
    stored = None
    for a in agent_store.list_agents():
        if a["name"] == "cli-agent":
            stored = a
    assert stored is not None and stored["default_vault_ids"] == ["ai"]
