"""Agent config snapshot: approval-time fingerprint and drift reapproval."""

import json

from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.tasks import planning, store
from obsidian_ai_hub.tasks import worker as task_worker
from obsidian_ai_hub.tasks.directional import (
    find_agent_config_drift,
    fingerprint_agent_config,
)
from obsidian_ai_hub.tasks.execution import ExecutorOutcome


def _context_for(agent_id=None):
    capabilities = [
        {
            "capability_key": "web_search",
            "adapter_kind": "registry_tool",
            "approval_policy": "auto",
        },
        {
            "capability_key": "specialist_agent",
            "adapter_kind": "agent",
            "approval_policy": "plan_required",
        },
    ]
    agents = [{"agent_id": agent_id, "name": "Helper"}] if agent_id else []
    return {"capabilities": capabilities, "agents": agents, "projects": []}


def _directional_dict(capabilities=("specialist_agent",)):
    return {
        "purpose": "調査を委譲する",
        "strategy": "専門Agentに依頼",
        "capabilities": [
            {"capability_key": key, "intent": f"use {key}"} for key in capabilities
        ],
        "constraints": "",
        "completion_criteria": "done",
        "max_actions": 5,
    }


def _to_running(task_id):
    store.transition_task_status(task_id, "planning")
    store.transition_task_status(task_id, "running")


def test_fingerprint_changes_with_prompt_and_tools():
    agent = agent_store.create_agent(name="Snap Agent", system_prompt="prompt A")
    first = fingerprint_agent_config(agent)
    assert first.system_prompt_sha256
    assert first.tool_ids == []

    agent_store.update_agent(agent["agent_id"], system_prompt="prompt B")
    second = fingerprint_agent_config(agent_store.get_agent(agent["agent_id"]))
    assert second != first
    assert find_agent_config_drift(
        {agent["agent_id"]: first.model_dump()},
        {agent["agent_id"]: second},
    ) == [agent["agent_id"]]


def test_drift_reports_deleted_and_ignores_empty_baseline():
    agent = agent_store.create_agent(name="Gone Agent", system_prompt="prompt")
    saved = {agent["agent_id"]: fingerprint_agent_config(agent).model_dump()}
    assert find_agent_config_drift(saved, {}) == [agent["agent_id"]]
    assert find_agent_config_drift({}, {}) == []


def test_validate_stamps_snapshot_and_discards_forged_value():
    agent = agent_store.create_agent(name="Stamp Agent", system_prompt="prompt")
    plan = _directional_dict()
    plan["agent_config_snapshot"] = {"forged": {"agent_id": "forged"}}
    snapshot = planning.validate_directional_plan(plan, _context_for(agent["agent_id"]))
    assert snapshot == {"specialist_agent": "plan_required"}
    assert plan["allowed_agent_ids"] == [agent["agent_id"]]
    assert set(plan["agent_config_snapshot"]) == {agent["agent_id"]}
    assert "forged" not in plan["agent_config_snapshot"]


def test_validate_without_specialist_leaves_snapshot_empty():
    plan = _directional_dict(capabilities=("web_search",))
    context = {
        "capabilities": [
            {
                "capability_key": "web_search",
                "adapter_kind": "registry_tool",
                "approval_policy": "auto",
            }
        ],
        "agents": [],
        "projects": [],
    }
    planning.validate_directional_plan(plan, context)
    assert plan["agent_config_snapshot"] == {}


def test_plan_task_persists_snapshot(monkeypatch):
    agent = agent_store.create_agent(name="Persist Agent", system_prompt="prompt")
    monkeypatch.setattr(
        planning, "collect_planner_context", lambda: _context_for(agent["agent_id"])
    )
    raw = json.dumps({"type": "plan", **_directional_dict()}, ensure_ascii=False)
    monkeypatch.setattr(planning, "generate_llm_response", lambda *a, **k: raw)
    task = store.create_task("snapshot job")
    claimed = store.claim_task("worker-test", "planning")
    assert claimed is not None
    result = planning.plan_task(task["task_id"])
    assert result["outcome"] == "waiting_approval"
    saved = result["plan"]["plan"]["agent_config_snapshot"]
    assert set(saved) == {agent["agent_id"]}


def test_worker_blocks_on_prompt_drift():
    agent = agent_store.create_agent(name="Drift Agent", system_prompt="before")
    plan_inner = {
        "plan_version": 2,
        **_directional_dict(),
        "allowed_agent_ids": [agent["agent_id"]],
        "allowed_project_ids": [],
        "agent_config_snapshot": {
            agent["agent_id"]: fingerprint_agent_config(agent).model_dump()
        },
    }
    task = store.create_task("drift job")
    plan = store.create_plan(
        task["task_id"], plan_inner, {"specialist_agent": "plan_required"}
    )
    _to_running(task["task_id"])
    agent_store.update_agent(agent["agent_id"], system_prompt="after")

    class ExplodingExecutor:
        def execute_step(self, *args, **kwargs):
            raise AssertionError("executor must not run on drift")

    task_worker._run_execution(task["task_id"], plan, ExplodingExecutor())
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "waiting_reapproval"
    events = store.list_task_events(task["task_id"])
    notes = [e for e in events if e["event_type"] == "note"]
    assert any(agent["agent_id"] in str(n["payload"]) for n in notes)
    assert len(store.list_plans(task["task_id"])) == 2


def test_worker_runs_when_snapshot_fresh(monkeypatch):
    import obsidian_ai_hub.tasks.orchestrator as orchestrator_module

    agent = agent_store.create_agent(name="Fresh Agent", system_prompt="stable")
    plan_inner = {
        "plan_version": 2,
        **_directional_dict(),
        "allowed_agent_ids": [agent["agent_id"]],
        "allowed_project_ids": [],
        "agent_config_snapshot": {
            agent["agent_id"]: fingerprint_agent_config(agent).model_dump()
        },
    }
    task = store.create_task("fresh job")
    plan = store.create_plan(
        task["task_id"], plan_inner, {"specialist_agent": "plan_required"}
    )
    _to_running(task["task_id"])
    monkeypatch.setattr(
        orchestrator_module,
        "run_directional_plan",
        lambda task_id, plan_record, executor=None, **kwargs: ExecutorOutcome(
            kind="completed", result_summary="ok"
        ),
    )
    task_worker._run_execution(task["task_id"], plan, None)
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "completed"


def test_worker_skips_plans_without_baseline():
    task = store.create_task("legacy job")
    plan_inner = {
        "plan_version": 2,
        **_directional_dict(),
        "allowed_agent_ids": [],
        "allowed_project_ids": [],
    }
    plan = store.create_plan(
        task["task_id"], plan_inner, {"specialist_agent": "plan_required"}
    )
    _to_running(task["task_id"])
    assert task_worker._ensure_agent_snapshot_fresh(task["task_id"], plan) is True
