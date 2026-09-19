"""Tests for registry-derived capability catalog, startup sync, skills adapter."""

import pytest

import obsidian_ai_hub.agents.registry as registry_module
from obsidian_ai_hub.runs import manager as run_manager
from obsidian_ai_hub.tasks import store
from obsidian_ai_hub.tasks.adapters.skills import SkillsAdapter
from obsidian_ai_hub.tasks.capabilities import (
    EXCLUDED_TOOL_IDS,
    get_capability_definitions,
    get_capability_keys,
)


def _fake_tool(name, result="ok"):
    class FakeSkillTool:
        def __init__(self):
            self.name = name
            self.calls = []

        def invoke(self, args):
            self.calls.append(args)
            return result

    return FakeSkillTool()


def test_catalog_derives_from_registry():
    live_ids = set(registry_module.TOOL_DEFINITIONS)
    keys = get_capability_keys()
    for tool_id in live_ids - EXCLUDED_TOOL_IDS:
        assert tool_id in keys, tool_id
    for excluded in EXCLUDED_TOOL_IDS:
        assert excluded not in keys
    # Delegate-only capabilities still exist.
    assert "specialist_agent" in keys
    assert "coding_cli" in keys


def test_catalog_policies_and_kinds():
    by_key = {d.key: d for d in get_capability_definitions()}
    assert by_key["web_search"].default_approval_policy == "auto"
    assert by_key["web_search"].adapter_kind == "registry_tool"
    assert by_key["run_shell"].default_approval_policy == "plan_required"
    assert by_key["skills"].adapter_kind == "skills"
    assert by_key["skills"].default_approval_policy == "plan_required"
    assert by_key["memory_propose"].adapter_kind == "memory"
    assert by_key["specialist_agent"].adapter_kind == "agent"
    assert by_key["coding_cli"].adapter_kind == "coding"
    # Read-only relation traversal is auto-approved like the other read tools.
    assert by_key["people_relations_walk"].adapter_kind == "registry_tool"
    assert by_key["people_relations_walk"].default_approval_policy == "auto"
    # Labels come from the registry.
    assert (
        by_key["web_search"].label
        == (registry_module.TOOL_DEFINITIONS["web_search"]["name"])
    )


def test_catalog_accepts_custom_plugin_tool():
    fake_registry = {
        "web_search": {"name": "Web検索", "description": "search"},
        "custom:my_tool": {"name": "My Tool", "description": "user plugin"},
    }
    definitions = {d.key: d for d in get_capability_definitions(fake_registry)}
    assert definitions["custom:my_tool"].adapter_kind == "registry_tool"
    assert definitions["custom:my_tool"].default_approval_policy == "plan_required"
    assert definitions["custom:my_tool"].label == "My Tool"
    assert definitions["web_search"].default_approval_policy == "auto"


def test_sync_capabilities_inserts_and_protects():
    before = {c["capability_key"]: c for c in store.list_capabilities()}
    store.update_capability("run_shell", enabled=False, approval_policy="auto")
    result = store.sync_capabilities()
    assert result["inserted"] == 0
    # DB-owned fields are protected by the sync.
    run_shell = store.get_capability("run_shell")
    assert run_shell is not None
    assert run_shell["enabled"] is False
    assert run_shell["approval_policy"] == "auto"
    assert run_shell["adapter_kind"] == "registry_tool"
    # Second sync is idempotent.
    assert store.sync_capabilities() == {"inserted": 0}
    assert {c["capability_key"] for c in store.list_capabilities()} == set(before)


def test_sync_capabilities_reinserts_missing():
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        conn.execute(
            "DELETE FROM task_agent_capabilities WHERE capability_key = 'run_shell';"
        )
        conn.commit()
    finally:
        conn.close()
    assert store.get_capability("run_shell") is None
    result = store.sync_capabilities()
    assert result["inserted"] == 1
    restored = store.get_capability("run_shell")
    assert restored is not None
    assert restored["enabled"] is True
    assert restored["approval_policy"] == "plan_required"


def test_startup_recovery_syncs_capabilities():
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        conn.execute(
            "DELETE FROM task_agent_capabilities WHERE capability_key = 'skills';"
        )
        conn.commit()
    finally:
        conn.close()
    run_manager.startup_recovery("live-instance")
    restored = store.get_capability("skills")
    assert restored is not None
    assert restored["adapter_kind"] == "skills"


def _task_with_skills_step(inputs):
    task = store.create_task("skills job")
    plan = store.create_plan(
        task["task_id"],
        {
            "purpose": "p",
            "steps": [
                {
                    "capability_key": "skills",
                    "title": "step",
                    "target": {},
                    "inputs": inputs,
                    "side_effects": "none",
                }
            ],
            "completion_criteria": "done",
        },
        {"skills": "plan_required"},
    )
    return task, plan


def test_skills_adapter_dispatch(monkeypatch):
    load_skill = _fake_tool("load_skill", "skill body")
    monkeypatch.setattr(
        registry_module,
        "TOOL_DEFINITIONS",
        {"skills": {"get_tools": lambda: [load_skill]}},
    )
    task, plan = _task_with_skills_step({"skill": "load_skill", "name": "notes"})
    result = SkillsAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])
    assert result.summary == "skill body"
    assert result.capability_key == "skills"
    assert load_skill.calls == [{"name": "notes"}]


def test_skills_adapter_unknown_skill(monkeypatch):
    load_skill = _fake_tool("load_skill")
    monkeypatch.setattr(
        registry_module,
        "TOOL_DEFINITIONS",
        {"skills": {"get_tools": lambda: [load_skill]}},
    )
    task, plan = _task_with_skills_step({"skill": "nope"})
    # The Literal schema rejects unknown skill names before dispatch.
    with pytest.raises(ValueError, match="inputs invalid"):
        SkillsAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])


def test_skills_adapter_rejects_non_skills_capability():
    task, plan = _task_with_skills_step({"skill": "load_skill"})
    bad_step = dict(plan["plan"]["steps"][0], capability_key="web_search")
    with pytest.raises(ValueError, match="not a skills capability"):
        SkillsAdapter().execute_step(task, plan, 0, bad_step)
