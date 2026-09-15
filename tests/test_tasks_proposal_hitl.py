"""Task Capability化した calendar/reminder 作成提案の契約テスト.

操作シナリオ契約: 承認済み auto Plan -> Runtime Worker が既存ツール経由で
提案HITL登録のみ行う (直接書込みなし)。人間の承認は既存提案HITL側で行う。
`plan_required` 時のPlan確認フローは従来どおり維持する。
"""

from __future__ import annotations

import json

import pytest

import obsidian_ai_hub.agents.registry as registry_module
from obsidian_ai_hub import hitl
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.tasks import capability_schemas as schemas
from obsidian_ai_hub.tasks import planning, store
from obsidian_ai_hub.tasks.adapters.registry_tools import RegistryToolExecutor
from obsidian_ai_hub.tasks.capabilities import (
    EXCLUDED_TOOL_IDS,
    get_capability_definitions,
)
from obsidian_ai_hub.tasks.orchestrator import run_directional_plan


CALENDAR_INPUTS = {
    "title": "歯医者",
    "start_time": "2026-09-20T14:00:00+09:00",
    "end_time": "2026-09-20T15:00:00+09:00",
}

REMINDER_INPUTS = {
    "title": "牛乳を買う",
    "due_date": "2026-09-20",
}


def _legacy_task_with_step(capability_key, inputs):
    task = store.create_task("proposal job")
    plan = store.create_plan(
        task["task_id"],
        {
            "purpose": "p",
            "steps": [
                {
                    "capability_key": capability_key,
                    "title": "step",
                    "target": {},
                    "inputs": inputs,
                    "side_effects": "proposal HITL only",
                }
            ],
            "completion_criteria": "done",
        },
        {capability_key: "auto"},
    )
    return task, plan


def test_proposal_capabilities_are_in_catalog():
    assert "calendar_create_proposal" not in EXCLUDED_TOOL_IDS
    assert "reminder_create_proposal" not in EXCLUDED_TOOL_IDS
    by_key = {d.key: d for d in get_capability_definitions()}
    assert by_key["calendar_create_proposal"].adapter_kind == "registry_tool"
    assert by_key["reminder_create_proposal"].adapter_kind == "registry_tool"
    assert by_key["calendar_create_proposal"].default_approval_policy == "auto"
    assert by_key["reminder_create_proposal"].default_approval_policy == "auto"


def test_proposal_schemas_resolve_and_validate():
    for key in ("calendar_create_proposal", "reminder_create_proposal"):
        assert schemas.resolve_input_model(key) is not None
        assert schemas.resolve_json_schema(key) is not None
        assert "title" in (schemas.compact_schema_text(key) or "")
    validated = schemas.validate_capability_inputs(
        "calendar_create_proposal", dict(CALENDAR_INPUTS)
    )
    assert validated["title"] == "歯医者"
    validated_reminder = schemas.validate_capability_inputs(
        "reminder_create_proposal", dict(REMINDER_INPUTS)
    )
    assert validated_reminder["title"] == "牛乳を買う"
    # 必須欠落はツール到達前に失敗する (安全境界の迂回なし)。
    with pytest.raises(ValueError, match="inputs invalid"):
        schemas.validate_capability_inputs("calendar_create_proposal", {})
    with pytest.raises(ValueError, match="inputs invalid"):
        schemas.validate_capability_inputs("reminder_create_proposal", {})


def test_registry_executor_registers_calendar_hitl_via_tool(test_memory_db_path):
    task, plan = _legacy_task_with_step(
        "calendar_create_proposal", dict(CALENDAR_INPUTS)
    )
    result = RegistryToolExecutor().execute_step(
        task, plan, 0, plan["plan"]["steps"][0]
    )
    payload = json.loads(result.summary)
    assert payload["status"] == "proposed"
    assert payload["hitl_run_id"]
    conn = get_db_connection()
    try:
        run = hitl.get_run(payload["hitl_run_id"], conn)
    finally:
        conn.close()
    assert run is not None
    assert run["handler"] == "calendar.add_approved_event"
    assert run["status"] == "pending_user"


def test_registry_executor_registers_reminder_hitl_via_tool(test_memory_db_path):
    task, plan = _legacy_task_with_step(
        "reminder_create_proposal", dict(REMINDER_INPUTS)
    )
    result = RegistryToolExecutor().execute_step(
        task, plan, 0, plan["plan"]["steps"][0]
    )
    payload = json.loads(result.summary)
    assert payload["status"] == "proposed"
    assert payload["hitl_run_id"]
    conn = get_db_connection()
    try:
        run = hitl.get_run(payload["hitl_run_id"], conn)
    finally:
        conn.close()
    assert run is not None
    assert run["handler"] == "reminders.add_approved_reminder"
    assert run["status"] == "pending_user"


def test_registry_executor_validates_before_hitl(test_memory_db_path, monkeypatch):
    from obsidian_ai_hub.calendar import hitl as calendar_hitl

    calls = []
    orig = calendar_hitl.register_calendar_event_approval

    def _recording(content, event):
        calls.append((content, event))
        return orig(content, event)

    monkeypatch.setattr(calendar_hitl, "register_calendar_event_approval", _recording)
    # registry.py は関数を直接import済みのため、参照側も差し替える。
    monkeypatch.setattr(registry_module, "register_calendar_event_approval", _recording)
    task, plan = _legacy_task_with_step("calendar_create_proposal", {})
    with pytest.raises(ValueError, match="inputs invalid"):
        RegistryToolExecutor().execute_step(task, plan, 0, plan["plan"]["steps"][0])
    assert calls == []


def test_registry_executor_uses_tool_route_not_direct_register(
    test_memory_db_path, monkeypatch
):
    """HITL登録を直接呼ばず、既存ツール経路を使うことを検証する."""
    from obsidian_ai_hub.calendar import hitl as calendar_hitl

    register_calls = []
    orig_register = calendar_hitl.register_calendar_event_approval

    def _recording_register(content, event):
        register_calls.append((content, event))
        return orig_register(content, event)

    monkeypatch.setattr(
        calendar_hitl, "register_calendar_event_approval", _recording_register
    )
    monkeypatch.setattr(
        registry_module, "register_calendar_event_approval", _recording_register
    )

    invoked = []
    live_meta = registry_module.TOOL_DEFINITIONS["calendar_create_proposal"]
    orig_get_tool = live_meta["get_tool"]
    orig_tool = orig_get_tool()
    orig_invoke = orig_tool.invoke

    class _RecordingTool:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            # Pydantic args_schema compatibility for schema resolution.
            self.args_schema = getattr(wrapped, "args_schema", None)
            self.name = getattr(wrapped, "name", "calendar_create_proposal")

        def invoke(self, inputs):
            invoked.append(dict(inputs))
            return orig_invoke(inputs)

    monkeypatch.setitem(
        registry_module.TOOL_DEFINITIONS,
        "calendar_create_proposal",
        {
            **live_meta,
            "get_tool": lambda: _RecordingTool(orig_tool),
        },
    )
    task, plan = _legacy_task_with_step(
        "calendar_create_proposal", dict(CALENDAR_INPUTS)
    )
    RegistryToolExecutor().execute_step(task, plan, 0, plan["plan"]["steps"][0])
    assert len(invoked) == 1
    assert invoked[0]["title"] == "歯医者"
    assert len(register_calls) == 1


def _directional_context(policies):
    return {
        "capabilities": [
            {
                "capability_key": key,
                "adapter_kind": "registry_tool",
                "approval_policy": policy,
            }
            for key, policy in policies.items()
        ],
        "agents": [],
        "projects": [],
    }


def _directional_json(capability_keys):
    return json.dumps(
        {
            "type": "plan",
            "purpose": "予定と買物を頼む",
            "strategy": "提案HITLに登録する",
            "capabilities": [
                {"capability_key": key, "intent": f"use {key}"}
                for key in capability_keys
            ],
            "constraints": "",
            "completion_criteria": "提案HITLが登録される",
            "max_actions": 5,
        },
        ensure_ascii=False,
    )


def _claim(task_id):
    claimed = store.claim_task("worker-test", "planning")
    assert claimed is not None
    assert claimed["task_id"] == task_id


def test_auto_proposal_plan_skips_confirmation(monkeypatch):
    policies = {
        "calendar_create_proposal": "auto",
        "reminder_create_proposal": "auto",
    }
    monkeypatch.setattr(
        planning, "collect_planner_context", lambda: _directional_context(policies)
    )
    raw = _directional_json(list(policies))
    monkeypatch.setattr(planning, "generate_llm_response", lambda *a, **k: raw)
    task = store.create_task("auto proposal job")
    _claim(task["task_id"])
    result = planning.plan_task(task["task_id"])
    assert result["outcome"] == "running"
    assert result["task"]["status"] == "running"
    assert result["plan"]["approval_policy_snapshot"] == policies


def test_plan_required_proposal_plan_still_waits_approval(monkeypatch):
    policies = {
        "calendar_create_proposal": "plan_required",
        "reminder_create_proposal": "auto",
    }
    monkeypatch.setattr(
        planning, "collect_planner_context", lambda: _directional_context(policies)
    )
    raw = _directional_json(list(policies))
    monkeypatch.setattr(planning, "generate_llm_response", lambda *a, **k: raw)
    task = store.create_task("plan_required proposal job")
    _claim(task["task_id"])
    result = planning.plan_task(task["task_id"])
    # auto以外は従来どおりPlan確認が必要。
    assert result["outcome"] == "waiting_approval"
    assert result["task"]["status"] == "waiting_approval"
    assert result["plan"]["approval_policy_snapshot"] == policies


def test_orchestrator_auto_proposal_registers_hitl(test_memory_db_path):
    task = store.create_task("orchestrator proposal job")
    plan = store.create_plan(
        task["task_id"],
        {
            "plan_version": 2,
            "purpose": "予定を頼む",
            "strategy": "提案HITLに登録する",
            "capabilities": [
                {
                    "capability_key": "calendar_create_proposal",
                    "intent": "予定の提案登録",
                }
            ],
            "constraints": "",
            "completion_criteria": "提案HITLが登録される",
            "max_actions": 5,
        },
        {"calendar_create_proposal": "auto"},
    )
    actions = [
        {
            "action": "call_capability",
            "capability_key": "calendar_create_proposal",
            "target": {},
            "inputs": dict(CALENDAR_INPUTS),
            "reason": "予定を提案登録する",
        },
        {"action": "finish", "summary": "提案HITLを登録した", "reason": "完了"},
    ]
    queue = list(actions)

    def _generate(prompt):
        assert queue, "generator called too many times"
        return queue.pop(0)

    outcome = run_directional_plan(
        task["task_id"], plan, RegistryToolExecutor(), _generate
    )
    assert outcome.kind == "completed"
    events = store.list_task_events(task["task_id"])
    completed = [e for e in events if e["event_type"] == "capability_completed"]
    assert len(completed) == 1
    payload = completed[0]["payload"]
    assert payload["capability_key"] == "calendar_create_proposal"
    assert payload["inputs"]["title"] == "歯医者"
    summary = json.loads(completed[0]["payload"]["observation"])
    assert summary["status"] == "proposed"
    conn = get_db_connection()
    try:
        run = hitl.get_run(summary["hitl_run_id"], conn)
    finally:
        conn.close()
    assert run is not None
    assert run["handler"] == "calendar.add_approved_event"
