"""Tests for the Runtime Orchestrator dynamic agent loop."""

import json

import pytest

import obsidian_ai_hub.tasks.orchestrator as orchestrator_module
from obsidian_ai_hub.tasks import planning, store
from obsidian_ai_hub.tasks import worker as task_worker
from obsidian_ai_hub.tasks.execution import StepResult, TaskCancelled
from obsidian_ai_hub.tasks.orchestrator import run_directional_plan


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def execute_step(self, task, plan, step_index, step):
        self.calls.append(
            (step_index, step["capability_key"], dict(step.get("inputs") or {}))
        )
        key = step["capability_key"]
        if key == "vault_search":
            return StepResult(
                step_index=step_index,
                capability_key=key,
                summary=json.dumps(
                    [{"content": "朝会は結論ファーストが好み", "score": 0.9}],
                    ensure_ascii=False,
                ),
            )
        if key == "memory_propose":
            return StepResult(
                step_index=step_index,
                capability_key=key,
                summary=json.dumps({"status": "candidate", "memory_id": "m1"}),
            )
        return StepResult(
            step_index=step_index, capability_key=key, summary='{"ok": true}'
        )


def _directional_plan(task_id, capabilities=("vault_search", "memory_propose")):
    return store.create_plan(
        task_id,
        {
            "plan_version": 2,
            "purpose": "好みを記憶する",
            "strategy": "検索してから提案",
            "capabilities": [
                {"capability_key": key, "intent": f"use {key}"}
                for key in capabilities
            ],
            "constraints": "記憶の推測禁止",
            "completion_criteria": "候補が作られる",
            "max_actions": 5,
        },
        {key: "auto" for key in capabilities},
    )


def _task_with_directional(capabilities=("vault_search", "memory_propose")):
    task = store.create_task("好みを記憶して")
    plan = _directional_plan(task["task_id"], capabilities)
    return task, plan


def _scripted(actions):
    queue = list(actions)

    def _generate(prompt):
        assert queue, "action generator called more times than scripted"
        action = queue.pop(0)
        if callable(action):
            return action(prompt)
        return action

    return _generate


def test_observation_flows_into_next_action():
    task, plan = _task_with_directional()
    executor = FakeExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "vault_search",
                "inputs": {"query": "好み"},
                "reason": "まず検索",
            },
            {
                "action": "call_capability",
                "capability_key": "memory_propose",
                "inputs": {"content": "朝会では結論から先に述べる", "kind": "fact"},
                "reason": "観測を記憶",
            },
            {"action": "finish", "summary": "候補を作成した", "reason": "完了"},
        ]
    )
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "completed"
    assert outcome.result_summary == "候補を作成した"
    assert [c[1] for c in executor.calls] == ["vault_search", "memory_propose"]
    # memory_propose inputs were schema-validated before the tool call.
    assert executor.calls[1][2]["kind"] == "fact"

    events = store.list_task_events(task["task_id"])
    completed = [e for e in events if e["event_type"] == "capability_completed"]
    assert len(completed) == 2
    assert completed[0]["payload"]["action_index"] == 0
    assert completed[1]["payload"]["inputs"]["kind"] == "fact"
    assert "朝会" in (completed[0]["payload"].get("observation") or "")


def test_unknown_key_rejected_then_self_corrected():
    task, plan = _task_with_directional(("memory_propose",))
    executor = FakeExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "memory_propose",
                "inputs": {
                    "content": "x",
                    "kind": "fact",
                    "source": "instruction",
                },
                "reason": "bad first try",
            },
            {
                "action": "call_capability",
                "capability_key": "memory_propose",
                "inputs": {"content": "x", "kind": "fact"},
                "reason": "fixed",
            },
            {"action": "finish", "summary": "done", "reason": "ok"},
        ]
    )
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "completed"
    assert len(executor.calls) == 1
    assert executor.calls[0][2] == {"content": "x", "kind": "fact"}
    events = store.list_task_events(task["task_id"])
    notes = [e for e in events if e["event_type"] == "note"]
    assert any("validation error" in (n["payload"].get("text") or "") for n in notes)


def test_self_correction_exhaustion_fails():
    task, plan = _task_with_directional(("memory_propose",))
    executor = FakeExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "memory_propose",
                "inputs": {"content": "x"},
                "reason": "missing kind",
            },
        ]
        * 5
    )
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "failed"
    assert "validation" in (outcome.error_summary or "")
    assert executor.calls == []


def test_out_of_scope_capability_goes_to_deviation():
    task, plan = _task_with_directional(("vault_search",))
    executor = FakeExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "memory_propose",
                "inputs": {"content": "x", "kind": "fact"},
                "reason": "scope外",
            }
        ]
    )
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "deviation"
    assert "memory_propose" in (outcome.deviation_reason or "")
    assert executor.calls == []


def test_invalid_action_shape_self_corrects_then_fails():
    task, plan = _task_with_directional()
    executor = FakeExecutor()
    generator = _scripted([{"action": "teleport", "reason": "???"}] * 5)
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "failed"
    assert executor.calls == []


def test_max_actions_stops_loop():
    task = store.create_task("終わらない仕事")
    plan = _directional_plan(task["task_id"], ("vault_search",))
    plan["plan"]["max_actions"] = 2
    executor = FakeExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "vault_search",
                "inputs": {"query": f"q{i}"},
                "reason": "loop",
            }
            for i in range(5)
        ]
    )
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "failed"
    assert "最大Action数" in (outcome.error_summary or "")
    assert len(executor.calls) == 2


def test_repeat_detection_stops_loop():
    task, plan = _task_with_directional(("vault_search",))
    executor = FakeExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "vault_search",
                "inputs": {"query": "same"},
                "reason": "again",
            },
        ]
        * 5
    )
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "failed"
    assert "反復" in (outcome.error_summary or "")
    # First call executes; the immediate repeat is corrected once, then stops.
    assert len(executor.calls) == 1


def test_tool_failure_marks_failed_with_event():
    task, plan = _task_with_directional(("vault_search",))

    class FailingExecutor:
        def execute_step(self, task, plan, step_index, step):
            raise ValueError("tool exploded")

    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "vault_search",
                "inputs": {"query": "x"},
                "reason": "try",
            }
        ]
    )
    outcome = run_directional_plan(task["task_id"], plan, FailingExecutor(), generator)
    assert outcome.kind == "failed"
    assert "tool exploded" in (outcome.error_summary or "")
    events = store.list_task_events(task["task_id"])
    assert any(e["event_type"] == "note" for e in events)


def test_resume_does_not_rerun_completed_actions():
    task, plan = _task_with_directional()
    store.append_task_event(
        task["task_id"],
        "capability_completed",
        {
            "action_index": 0,
            "step_index": 0,
            "capability_key": "vault_search",
            "inputs": {"query": "好み"},
            "summary": '[{"content": "prior"}]',
            "observation": '[{"content": "prior"}]',
        },
    )
    executor = FakeExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "memory_propose",
                "inputs": {"content": "prior", "kind": "fact"},
                "reason": "resume",
            },
            {"action": "finish", "summary": "resumed done", "reason": "ok"},
        ]
    )
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "completed"
    assert [c[1] for c in executor.calls] == ["memory_propose"]
    assert executor.calls[0][0] == 1


def test_child_deviation_creates_revised_plan_and_deviates():
    from obsidian_ai_hub.tasks.execution import DeviationReported

    task, plan = _task_with_directional(("vault_search",))

    class DeviatingExecutor:
        def execute_step(self, task, plan, step_index, step):
            raise DeviationReported(
                {
                    "purpose": "revised",
                    "steps": [
                        {
                            "capability_key": "vault_search",
                            "title": "extra",
                            "target": {},
                            "inputs": {"query": "y"},
                        }
                    ],
                    "completion_criteria": "done",
                },
                "need more search",
            )

    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "vault_search",
                "inputs": {"query": "x"},
                "reason": "try",
            }
        ]
    )
    outcome = run_directional_plan(task["task_id"], plan, DeviatingExecutor(), generator)
    assert outcome.kind == "deviation"
    assert "need more search" in (outcome.deviation_reason or "")
    plans = store.list_plans(task["task_id"])
    assert len(plans) == 2
    assert isinstance(plans[1]["plan"].get("steps"), list)


def test_cancel_during_loop_propagates():
    task, plan = _task_with_directional()
    store.claim_task("worker-1", "planning")
    store.transition_task_status(task["task_id"], "running")
    store.transition_task_status(task["task_id"], "cancelling")
    with pytest.raises(TaskCancelled):
        run_directional_plan(
            task["task_id"],
            plan,
            FakeExecutor(),
            _scripted(
                [
                    {
                        "action": "call_capability",
                        "capability_key": "vault_search",
                        "inputs": {"query": "x"},
                        "reason": "try",
                    }
                ]
            ),
        )


def test_events_and_prompt_redact_secrets(monkeypatch):
    # Patch at the redaction layer (not the config module object): an older
    # test module replaces sys.modules["obsidian_ai_hub.utils.config"], so
    # patching the config object is order-dependent. This targets exactly
    # what redact_text() consults.
    from obsidian_ai_hub.tasks import redaction

    monkeypatch.setattr(
        redaction, "configured_secret_values", lambda: ("secret-xyz-123",)
    )
    task, plan = _task_with_directional(("memory_propose",))
    executor = FakeExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "memory_propose",
                "inputs": {"content": "key secret-xyz-123 note", "kind": "fact"},
                "reason": "with secret",
            },
            {"action": "finish", "summary": "done", "reason": "ok"},
        ]
    )
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "completed"
    events = store.list_task_events(task["task_id"])
    completed = [e for e in events if e["event_type"] == "capability_completed"]
    assert "secret-xyz-123" not in json.dumps(completed[0]["payload"])
    assert "[REDACTED]" in json.dumps(completed[0]["payload"])

    prompt = orchestrator_module.build_orchestrator_prompt(
        {"prompt_text": "hello secret-xyz-123"},
        orchestrator_module.DirectionalPlan(
            purpose="p",
            capabilities=[{"capability_key": "memory_propose", "intent": "i"}],
            completion_criteria="d",
        ),
        {"capability_keys": ["memory_propose"]},
        {"memory_propose": "content string required"},
        [],
    )
    assert "secret-xyz-123" not in prompt


def test_worker_runs_directional_plan_end_to_end(monkeypatch):
    directional_json = json.dumps(
        {
            "type": "plan",
            "purpose": "好みを記憶する",
            "strategy": "検索して提案",
            "capabilities": [
                {"capability_key": "vault_search", "intent": "検索"},
                {"capability_key": "memory_propose", "intent": "提案"},
            ],
            "constraints": "",
            "completion_criteria": "候補作成",
            "max_actions": 5,
        }
    )
    monkeypatch.setattr(
        planning,
        "collect_planner_context",
        lambda: {
            "capabilities": [
                {
                    "capability_key": "vault_search",
                    "adapter_kind": "registry_tool",
                    "approval_policy": "auto",
                },
                {
                    "capability_key": "memory_propose",
                    "adapter_kind": "memory",
                    "approval_policy": "auto",
                },
            ],
            "agents": [],
            "projects": [],
        },
    )
    monkeypatch.setattr(
        planning, "generate_llm_response", lambda *a, **k: directional_json
    )

    from obsidian_ai_hub.handler.web_search import WebSearchInput

    import obsidian_ai_hub.agents.registry as registry_module

    vault_calls = []
    propose_calls = []

    class FakeTool:
        def __init__(self, name, bucket):
            self._name = name
            self._bucket = bucket

        def invoke(self, inputs):
            self._bucket.append(inputs)
            if self._name == "vault_search":
                return '[{"content": "x"}]'
            return '{"status": "candidate"}'

    monkeypatch.setattr(
        registry_module,
        "TOOL_DEFINITIONS",
        {
            "vault_search": {
                "get_tool": lambda: FakeTool("vault_search", vault_calls),
                "input_model": WebSearchInput,
            },
            "memory_propose": {
                "get_tool": lambda: FakeTool("memory_propose", propose_calls),
                "get_tool_with_context": lambda ctx: FakeTool(
                    "memory_propose", propose_calls
                ),
                "input_model": registry_module.MemoryProposeInput,
            },
        },
    )
    shared_script = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "vault_search",
                "inputs": {"query": "好み"},
                "reason": "search",
            },
            {
                "action": "call_capability",
                "capability_key": "memory_propose",
                "inputs": {"content": "朝会は結論ファースト", "kind": "fact"},
                "reason": "propose",
            },
            {"action": "finish", "summary": "完了", "reason": "ok"},
        ]
    )
    monkeypatch.setattr(
        orchestrator_module,
        "_default_generator",
        lambda task_id, index: shared_script,
    )
    task = store.create_task("好みを記憶して")
    assert task_worker._process_one("worker-1", None) is True
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["result_summary"] == "完了"
    assert len(vault_calls) == 1 and len(propose_calls) == 1


def test_target_scope_violation_goes_to_deviation():
    task, plan = _task_with_directional(("specialist_agent",))
    plan_record = dict(plan)
    plan_record["plan"] = dict(
        plan["plan"], allowed_agent_ids=["agent_allowed"]
    )
    executor = FakeExecutor()
    bad_action = {
        "action": "call_capability",
        "capability_key": "specialist_agent",
        "target": {"agent_id": "agent_evil"},
        "inputs": {"task": "do it"},
        "reason": "evil",
    }
    generator = _scripted([bad_action, bad_action, bad_action])
    outcome = run_directional_plan(task["task_id"], plan_record, executor, generator)
    assert outcome.kind == "deviation"
    assert "agent_evil" in (outcome.deviation_reason or "")
    assert executor.calls == []
    events = store.list_task_events(task["task_id"])
    assert any(
        "validation error" in (e["payload"].get("text") or "")
        for e in events
        if e["event_type"] == "note"
    )


def test_target_scope_allows_approved_agent():
    task, plan = _task_with_directional(("specialist_agent",))
    plan_record = dict(plan)
    plan_record["plan"] = dict(
        plan["plan"], allowed_agent_ids=["agent_1"]
    )

    class AgentExecutor(FakeExecutor):
        def execute_step(self, task, plan, step_index, step):
            self.calls.append(
                (step_index, step["capability_key"], dict(step.get("inputs") or {}))
            )
            return StepResult(
                step_index=step_index,
                capability_key="specialist_agent",
                summary="agent done",
            )

    executor = AgentExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "specialist_agent",
                "target": {"agent_id": "agent_1"},
                "inputs": {"task": "help"},
                "reason": "delegate",
            },
            {"action": "finish", "summary": "done", "reason": "ok"},
        ]
    )
    outcome = run_directional_plan(task["task_id"], plan_record, executor, generator)
    assert outcome.kind == "completed"
    assert len(executor.calls) == 1


def test_prompt_redacts_history_observations(monkeypatch):
    from obsidian_ai_hub.tasks import redaction

    monkeypatch.setattr(
        redaction, "configured_secret_values", lambda: ("history-secret-1",)
    )
    prompt = orchestrator_module.build_orchestrator_prompt(
        {"prompt_text": "hello"},
        orchestrator_module.DirectionalPlan(
            purpose="p",
            capabilities=[{"capability_key": "memory_propose", "intent": "i"}],
            completion_criteria="d",
        ),
        {"capability_keys": ["memory_propose"]},
        {"memory_propose": "content string required"},
        [
            {
                "action_index": 0,
                "capability_key": "vault_search",
                "inputs": {"query": "history-secret-1 leak"},
                "observation": "result history-secret-1 leak",
            }
        ],
    )
    assert "history-secret-1" not in prompt
    assert "[REDACTED]" in prompt


def _directional_plan_with_scope(task_id, capabilities, allowed_agents=None, allowed_projects=None):
    return store.create_plan(
        task_id,
        {
            "plan_version": 2,
            "purpose": "委譲テスト",
            "strategy": "",
            "capabilities": [
                {"capability_key": key, "intent": f"use {key}"}
                for key in capabilities
            ],
            "allowed_agent_ids": list(allowed_agents or []),
            "allowed_project_ids": list(allowed_projects or []),
            "constraints": "",
            "completion_criteria": "done",
            "max_actions": 6,
        },
        {key: "plan_required" for key in capabilities},
    )


def test_out_of_scope_agent_target_goes_to_deviation():
    task = store.create_task("委譲ジョブ")
    plan = _directional_plan_with_scope(
        task["task_id"], ("specialist_agent",), allowed_agents=["agent_1"]
    )
    executor = FakeExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "specialist_agent",
                "target": {"agent_id": "agent_evil"},
                "inputs": {"task": "do it"},
                "reason": "scope外",
            }
        ]
        * 5
    )
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "deviation"
    assert "agent_evil" in (outcome.deviation_reason or "")
    assert executor.calls == []


def test_out_of_scope_project_target_goes_to_deviation():
    task = store.create_task("codingジョブ")
    plan = _directional_plan_with_scope(
        task["task_id"], ("coding_cli",), allowed_projects=[7]
    )
    executor = FakeExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "coding_cli",
                "target": {"project_id": 999},
                "inputs": {"task": "hack"},
                "reason": "scope外",
            }
        ]
        * 5
    )
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "deviation"
    assert "999" in (outcome.deviation_reason or "")
    assert executor.calls == []


def test_resume_with_gapped_indices_continues_after_max():
    task = store.create_task("再開ジョブ")
    plan = _directional_plan(task["task_id"], ("vault_search",))
    for index in (0, 2):
        store.append_task_event(
            task["task_id"],
            "capability_completed",
            {
                "action_index": index,
                "step_index": index,
                "capability_key": "vault_search",
                "inputs": {"query": f"q{index}"},
                "summary": "obs",
                "observation": "obs",
            },
        )
    executor = FakeExecutor()
    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "vault_search",
                "inputs": {"query": "q3"},
                "reason": "continue",
            },
            {"action": "finish", "summary": "done", "reason": "ok"},
        ]
    )
    outcome = run_directional_plan(task["task_id"], plan, executor, generator)
    assert outcome.kind == "completed"
    # Gapped history (0, 2) resumes at max+1 = 3, no replay, no collision.
    assert [c[0] for c in executor.calls] == [3]


def test_deviation_rebuild_preserves_completed_targets():
    from obsidian_ai_hub.tasks.execution import DeviationReported

    task = store.create_task("逸脱ジョブ")
    plan = _directional_plan_with_scope(
        task["task_id"], ("specialist_agent",), allowed_agents=["agent_1"]
    )
    store.append_task_event(
        task["task_id"],
        "capability_completed",
        {
            "action_index": 0,
            "step_index": 0,
            "capability_key": "specialist_agent",
            "target": {"agent_id": "agent_1"},
            "inputs": {"task": "first"},
            "summary": "done1",
            "observation": "done1",
        },
    )

    class DeviatingExecutor:
        def execute_step(self, task, plan, step_index, step):
            raise DeviationReported(
                {
                    "purpose": "revised",
                    "steps": [
                        {
                            "capability_key": "vault_search",
                            "title": "extra",
                            "target": {},
                            "inputs": {"query": "y"},
                        }
                    ],
                    "completion_criteria": "done",
                },
                "need search too",
            )

    generator = _scripted(
        [
            {
                "action": "call_capability",
                "capability_key": "specialist_agent",
                "target": {"agent_id": "agent_1"},
                "inputs": {"task": "second"},
                "reason": "try",
            }
        ]
    )
    outcome = run_directional_plan(
        task["task_id"], plan, DeviatingExecutor(), generator
    )
    assert outcome.kind == "deviation"
    plans = store.list_plans(task["task_id"])
    rebuilt = plans[-1]["plan"]["steps"][0]
    assert rebuilt["target"] == {"agent_id": "agent_1"}
