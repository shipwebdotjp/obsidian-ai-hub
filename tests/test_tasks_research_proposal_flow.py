"""Integration scenario: effect-contract research proposal Task.

The plan allows four read capabilities plus the proposal capability. The
Runtime Orchestrator runs the reads and the proposal; because
``research_theme_propose`` establishes the machine-checkable
``research_theme_registered`` effect, the run completes as soon as it holds,
without waiting for an LLM ``finish`` action. Re-running after a crash between
the proposal side effect and its completion event must not register a second
HITL candidate because registration is idempotent per Task ID.
"""

import json


import obsidian_ai_hub.agents.registry as registry_module
from obsidian_ai_hub.tasks import store
from obsidian_ai_hub.tasks.adapters import get_default_executor
from obsidian_ai_hub.tasks.orchestrator import run_directional_plan

READ_CAPABILITIES = (
    "research_context_snapshot",
    "activity_search",
    "research_theme_history_search",
    "periodic_note_read",
)
PROPOSAL = "research_theme_propose"


class _ReadTool:
    def invoke(self, inputs):
        # Long enough to exercise the detail/gist split on the latest read.
        return json.dumps(
            {"activities": ["Task Agent実装"], "themes": ["リサーチ"]}
        ) + ("x" * 9000)


class _ProposeTool:
    def __init__(self, ctx, candidates, fail_after_register):
        self._ctx = ctx
        self._candidates = candidates
        self._fail_after_register = fail_after_register

    def invoke(self, inputs):
        task_id = self._ctx.get("task_id")
        if task_id in self._candidates:
            return json.dumps(
                {"status": "already_proposed", "theme_id": "t1", "hitl_run_id": "h1"}
            )
        self._candidates.append(task_id)
        if self._fail_after_register:
            # Simulate a crash between the candidate write and the
            # capability_completed event.
            raise RuntimeError("crash after candidate registration")
        return json.dumps(
            {"status": "candidate", "theme_id": "t1", "hitl_run_id": "h1"}
        )


def _install_tools(monkeypatch, candidates, seen_contexts, fail_after_register):
    def read_factory():
        return _ReadTool()

    def propose_factory(ctx):
        seen_contexts.append(ctx)
        return _ProposeTool(ctx, candidates, fail_after_register)

    monkeypatch.setattr(
        registry_module,
        "TOOL_DEFINITIONS",
        {
            "research_context_snapshot": {
                "get_tool": read_factory,
                "input_model": registry_module.ResearchContextSnapshotInput,
            },
            "activity_search": {
                "get_tool": read_factory,
                "input_model": registry_module.ActivitySearchInput,
            },
            "research_theme_history_search": {
                "get_tool": read_factory,
                "input_model": registry_module.ResearchThemeHistorySearchInput,
            },
            "periodic_note_read": {
                "get_tool": read_factory,
                "input_model": registry_module.PeriodicNoteReadInput,
            },
            "research_theme_propose": {
                "get_tool": propose_factory,
                "get_tool_with_context": propose_factory,
                "input_model": registry_module.ResearchThemeProposeInput,
            },
        },
    )


def _plan(task_id, max_actions=6):
    return store.create_plan(
        task_id,
        {
            "plan_version": 2,
            "purpose": "最適なリサーチテーマを1件提案する",
            "strategy": "文脈を読んでから提案する",
            "capabilities": [
                {"capability_key": key, "intent": f"use {key}"}
                for key in (*READ_CAPABILITIES, PROPOSAL)
            ],
            "constraints": "",
            "completion_criteria": "research_theme_proposeで1件登録しfinishする",
            "max_actions": max_actions,
        },
        {key: "auto" for key in (*READ_CAPABILITIES, PROPOSAL)},
    )


def _read_actions():
    return [
        {"action": "call_capability", "capability_key": "research_context_snapshot",
         "inputs": {}, "reason": "snapshot"},
        {"action": "call_capability", "capability_key": "activity_search",
         "inputs": {"limit": 10}, "reason": "activities"},
        {"action": "call_capability", "capability_key": "research_theme_history_search",
         "inputs": {"limit": 10}, "reason": "themes"},
        {"action": "call_capability", "capability_key": "periodic_note_read",
         "inputs": {"period_type": "day", "reference_date": "2026-09-16"},
         "reason": "daily note"},
    ]


def _scripted(actions):
    queue = list(actions)

    def _generate(prompt):
        assert queue, "action generator called too many times"
        return queue.pop(0)

    return _generate


def test_six_action_research_proposal_registers_one_candidate(monkeypatch):
    candidates: list[str] = []
    seen_contexts: list[dict] = []
    _install_tools(monkeypatch, candidates, seen_contexts, fail_after_register=False)

    task = store.create_task("リサーチテーマを提案して")
    plan = _plan(task["task_id"])
    generator = _scripted(
        _read_actions()
        + [
            {"action": "call_capability", "capability_key": PROPOSAL,
             "inputs": {"theme": "エッジAIの量子化"}, "reason": "propose"},
        ]
    )
    outcome = run_directional_plan(
        task["task_id"], plan, get_default_executor(), generator
    )

    assert outcome.kind == "completed"
    assert "research_theme_registered" in (outcome.result_summary or "")
    assert candidates == [task["task_id"]]
    assert seen_contexts[0]["task_id"] == task["task_id"]

    events = store.list_task_events(task["task_id"])
    completed = [e for e in events if e["event_type"] == "capability_completed"]
    assert [e["payload"]["action_index"] for e in completed] == [0, 1, 2, 3, 4]
    # Each action stores both the display detail and the reusable gist.
    for event in completed:
        payload = event["payload"]
        assert payload["observation"]
        assert payload["observation_summary"]
        assert len(payload["observation_summary"]) <= 1600


def test_resume_after_crash_does_not_register_second_candidate(monkeypatch):
    candidates: list[str] = []
    seen_contexts: list[dict] = []
    _install_tools(monkeypatch, candidates, seen_contexts, fail_after_register=True)

    task = store.create_task("リサーチテーマを提案して")
    plan = _plan(task["task_id"])

    # Run 1: four reads complete, then the proposal side effect happens but
    # the run crashes before its completion event. Reads are seeded as
    # completed so the resume starts at the proposal.
    for index, key in enumerate(READ_CAPABILITIES):
        store.append_task_event(
            task["task_id"],
            "capability_completed",
            {
                "action_index": index,
                "step_index": index,
                "capability_key": key,
                "inputs": {},
                "summary": "read observation",
                "observation": "read observation",
                "observation_summary": "read gist",
            },
        )
    crash = run_directional_plan(
        task["task_id"],
        plan,
        get_default_executor(),
        _scripted(
            [
                {"action": "call_capability", "capability_key": PROPOSAL,
                 "inputs": {"theme": "エッジAIの量子化"}, "reason": "propose"},
            ]
        ),
    )
    assert crash.kind == "failed"
    assert candidates == [task["task_id"]]

    # Run 2 (resume): the proposal is retried with the same Task ID.
    _install_tools(monkeypatch, candidates, seen_contexts, fail_after_register=False)
    resume = run_directional_plan(
        task["task_id"],
        plan,
        get_default_executor(),
        _scripted(
            [
                {"action": "call_capability", "capability_key": PROPOSAL,
                 "inputs": {"theme": "エッジAIの量子化"}, "reason": "retry"},
                {"action": "finish", "summary": "再開して完了", "reason": "done"},
            ]
        ),
    )
    assert resume.kind == "completed"
    # The handler is keyed by Task ID: no second candidate.
    assert candidates == [task["task_id"]]
    assert seen_contexts[-1]["task_id"] == task["task_id"]


def test_finish_before_proposal_is_rejected_then_completes(monkeypatch):
    candidates: list[str] = []
    seen_contexts: list[dict] = []
    _install_tools(monkeypatch, candidates, seen_contexts, fail_after_register=False)

    task = store.create_task("リサーチテーマを提案して")
    plan = _plan(task["task_id"])
    generator = _scripted(
        [
            {"action": "finish", "summary": "まだだけど完了", "reason": "premature"},
            {"action": "call_capability", "capability_key": PROPOSAL,
             "inputs": {"theme": "エッジAIの量子化"}, "reason": "propose"},
        ]
    )
    outcome = run_directional_plan(
        task["task_id"], plan, get_default_executor(), generator
    )

    assert outcome.kind == "completed"
    assert candidates == [task["task_id"]]
    notes = [
        e for e in store.list_task_events(task["task_id"]) if e["event_type"] == "note"
    ]
    assert any(
        "required effects unmet" in json.dumps(e["payload"]) for e in notes
    )


def test_unmet_required_effect_at_budget_is_incomplete(monkeypatch):
    candidates: list[str] = []
    seen_contexts: list[dict] = []
    _install_tools(monkeypatch, candidates, seen_contexts, fail_after_register=False)

    task = store.create_task("リサーチテーマを提案して")
    plan = _plan(task["task_id"], max_actions=2)
    generator = _scripted(
        [
            {"action": "call_capability", "capability_key": "research_context_snapshot",
             "inputs": {}, "reason": "read"},
            {"action": "call_capability", "capability_key": "activity_search",
             "inputs": {"limit": 10}, "reason": "read"},
        ]
    )
    outcome = run_directional_plan(
        task["task_id"], plan, get_default_executor(), generator
    )

    assert outcome.kind == "incomplete"
    assert "research_theme_registered" in (outcome.error_summary or "")
    assert candidates == []


def test_resume_reconstructs_satisfied_effects(monkeypatch):
    candidates: list[str] = []
    seen_contexts: list[dict] = []
    _install_tools(monkeypatch, candidates, seen_contexts, fail_after_register=False)

    task = store.create_task("リサーチテーマを提案して")
    plan = _plan(task["task_id"], max_actions=1)
    store.append_task_event(
        task["task_id"],
        "capability_completed",
        {
            "action_index": 0,
            "step_index": 0,
            "capability_key": PROPOSAL,
            "inputs": {"theme": "エッジAIの量子化"},
            "summary": "candidate",
            "observation": "candidate",
            "observation_summary": "candidate",
            "effects_satisfied": ["research_theme_registered"],
        },
    )

    def _must_not_run(prompt):
        raise AssertionError("generator must not run once effects are satisfied")

    outcome = run_directional_plan(
        task["task_id"], plan, get_default_executor(), _must_not_run
    )

    assert outcome.kind == "completed"
    assert "research_theme_registered" in (outcome.result_summary or "")
