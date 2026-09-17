import asyncio
import json

import pytest

from obsidian_ai_hub.runs import manager as run_manager
from obsidian_ai_hub.tasks import execution, planning, store
from obsidian_ai_hub.tasks import worker as task_worker


def _auto_plan_json():
    return json.dumps(
        {
            "type": "plan",
            "purpose": "Do the thing",
            "steps": [
                {
                    "capability_key": "web_search",
                    "title": "Search",
                    "target": {},
                    "inputs": {"query": "x"},
                    "side_effects": "none",
                }
            ],
            "completion_criteria": "done",
        }
    )


def _context():
    return {
        "capabilities": [
            {
                "capability_key": "web_search",
                "adapter_kind": "registry_tool",
                "approval_policy": "auto",
            },
            {
                "capability_key": "coding_cli",
                "adapter_kind": "coding",
                "approval_policy": "plan_required",
            },
        ],
        "agents": [],
        "projects": [
            {"project_id": "proj_1", "name": "Demo", "git_root": "/repo/demo"}
        ],
    }


class FakeExecutor:
    def __init__(self, summary="fake done"):
        self.summary = summary
        self.calls = []

    def execute_step(self, task, plan, step_index, step):
        self.calls.append((step_index, step["capability_key"]))
        return execution.StepResult(
            step_index=step_index,
            capability_key=step["capability_key"],
            summary=self.summary,
        )


def _patch_llm(monkeypatch, raw):
    monkeypatch.setattr(planning, "collect_planner_context", _context)
    monkeypatch.setattr(planning, "generate_llm_response", lambda *a, **k: raw)


def test_process_one_auto_only_completes(monkeypatch):
    _patch_llm(monkeypatch, _auto_plan_json())
    executor = FakeExecutor()
    task = store.create_task("auto job")
    assert task_worker._process_one("worker-1", executor) is True
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["result_summary"] == "fake done"
    assert executor.calls == [(0, "web_search")]
    events = store.list_task_events(task["task_id"])
    assert "capability_completed" in [e["event_type"] for e in events]


def test_process_one_plan_required_waits_then_executes(monkeypatch):
    plan = json.loads(_auto_plan_json())
    plan["steps"][0]["capability_key"] = "coding_cli"
    plan["steps"][0]["target"] = {"project_id": "proj_1"}
    _patch_llm(monkeypatch, json.dumps(plan))
    executor = FakeExecutor()
    task = store.create_task("coding job")
    assert task_worker._process_one("worker-1", executor) is True
    assert store.get_task(task["task_id"])["status"] == "waiting_approval"
    assert executor.calls == []

    store.decide_plan(task["task_id"], "approve")
    assert task_worker._process_one("worker-1", executor) is True
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "completed"
    assert executor.calls == [(0, "coding_cli")]


def test_process_one_question_waits_user(monkeypatch):
    _patch_llm(
        monkeypatch,
        json.dumps({"type": "question", "question_text": "Which?"}),
    )
    task = store.create_task("ambiguous job")
    assert task_worker._process_one("worker-1", FakeExecutor()) is True
    assert store.get_task(task["task_id"])["status"] == "waiting_user"


def test_process_one_planner_failure_marks_failed(monkeypatch):
    _patch_llm(monkeypatch, "not json")
    task = store.create_task("broken job")
    assert task_worker._process_one("worker-1", FakeExecutor()) is True
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "failed"


def test_process_one_unconnected_executor_fails(monkeypatch):
    _patch_llm(monkeypatch, _auto_plan_json())
    task = store.create_task("no adapters job")
    assert task_worker._process_one("worker-1", execution.UnconnectedExecutor()) is True
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "failed"
    assert "No adapter connected" in (updated["error_summary"] or "")


def test_process_one_deviation_revises_plan(monkeypatch):
    _patch_llm(monkeypatch, _auto_plan_json())

    class DeviatingExecutor(FakeExecutor):
        def execute_step(self, task, plan, step_index, step):
            raise execution.DeviationReported(
                {
                    "purpose": "revised",
                    "steps": [dict(step, title="revised step")],
                    "completion_criteria": "revised done",
                },
                "need coding instead",
            )

    task = store.create_task("deviating job")
    assert task_worker._process_one("worker-1", DeviatingExecutor()) is True
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "waiting_reapproval"
    plans = store.list_plans(task["task_id"])
    assert [p["version"] for p in plans] == [1, 2]
    assert plans[0]["status"] == "superseded"
    assert plans[1]["status"] == "pending"


def test_execute_plan_empty_steps_fails():
    task = store.create_task("empty plan job")
    store.claim_task("worker-1", "planning")
    store.transition_task_status(task["task_id"], "running")
    outcome = execution.execute_plan(
        task["task_id"],
        {"plan_id": "tplan_x", "plan": {"steps": []}},
        FakeExecutor(),
    )
    assert outcome.kind == "failed"
    assert "no steps" in (outcome.error_summary or "")


def test_plan_task_rejects_stale_planning_state(monkeypatch):
    _patch_llm(monkeypatch, _auto_plan_json())
    task = store.create_task("stale job")
    # Never claimed: still queued when the planner finishes.
    with pytest.raises(ValueError, match="no longer in 'planning'"):
        planning.plan_task(task["task_id"])
    assert store.list_plans(task["task_id"]) == []
    assert store.get_task(task["task_id"])["status"] == "queued"


def test_process_one_planner_crash_marks_failed(monkeypatch):
    def _crash(task_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(task_worker, "plan_task", _crash)
    task = store.create_task("crash job")
    assert task_worker._process_one("worker-1", FakeExecutor()) is True
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "failed"
    assert "boom" in (updated["error_summary"] or "")


def test_task_worker_loop_processes_queued(monkeypatch):
    _patch_llm(monkeypatch, _auto_plan_json())
    task = store.create_task("loop job")

    async def _run():
        stop = asyncio.Event()
        loop_task = asyncio.create_task(
            task_worker.task_worker_loop(
                "worker-loop", stop, poll_interval=0.01, executor=FakeExecutor()
            )
        )
        for _ in range(200):
            current = store.get_task(task["task_id"])
            if current and current["status"] == "completed":
                break
            await asyncio.sleep(0.05)
        stop.set()
        await loop_task

    asyncio.run(_run())
    assert store.get_task(task["task_id"])["status"] == "completed"


def test_mark_stale_tasks_interrupted():
    store.create_task("stale running")
    stale = store.claim_task("dead-instance", "planning")
    assert stale is not None
    store.transition_task_status(stale["task_id"], "running")
    store.create_task("fresh")
    fresh = store.claim_task("live-instance", "planning")
    assert fresh is not None

    assert store.mark_stale_tasks_interrupted("live-instance") == 1
    assert store.get_task(stale["task_id"])["status"] == "interrupted"
    assert store.get_task(fresh["task_id"])["status"] == "planning"


def test_startup_recovery_covers_tasks():
    store.create_task("orphan")
    orphan = store.claim_task("dead-instance", "planning")
    assert orphan is not None
    result = run_manager.startup_recovery("live-instance")
    assert result["task_interrupted"] == 1
    assert store.get_task(orphan["task_id"])["status"] == "interrupted"


def test_startup_recovery_purges_old_terminal_tasks():
    from obsidian_ai_hub.database import get_db_connection

    old = store.create_task("old terminal")
    store.claim_task("dead-instance", "planning")
    store.transition_task_status(old["task_id"], "running")
    store.transition_task_status(old["task_id"], "completed")
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE task_agent_tasks SET finished_at = '2000-01-01T00:00:00+00:00' "
            "WHERE task_id = ?;",
            (old["task_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    recent = store.create_task("recent terminal")
    store.claim_task("dead-instance", "planning")
    store.transition_task_status(recent["task_id"], "running")
    store.transition_task_status(recent["task_id"], "completed")

    run_manager.startup_recovery("live-instance")
    assert store.get_task(old["task_id"]) is None
    assert store.get_task(recent["task_id"]) is not None


def test_shutdown_recovery_covers_tasks():
    store.create_task("mine")
    mine = store.claim_task("this-instance", "planning")
    assert mine is not None
    result = run_manager.shutdown_recovery("this-instance")
    assert result["task_interrupted"] == 1
    assert store.get_task(mine["task_id"])["status"] == "interrupted"


def _v3_coding_plan(task_id, project_id=7):
    return store.create_plan(
        task_id,
        {
            "plan_version": 3,
            "purpose": "実装する",
            "strategy": "codingする",
            "capabilities": [{"capability_key": "coding_cli", "intent": "実装"}],
            "allowed_agent_ids": [],
            "allowed_project_ids": [project_id],
            "project_resolution": {
                "kind": "project",
                "project_id": project_id,
                "display_name": "Demo",
                "confidence": None,
                "rationale": "人間が選択した対象",
                "source": "user",
            },
            "constraints": "",
            "completion_criteria": "done",
            "max_actions": 5,
        },
        {"coding_cli": "plan_required"},
    )


def _ready_for_execution(task_id):
    store.sync_capabilities()
    store.claim_task("worker-1", "planning")
    store.transition_task_status(task_id, "waiting_approval")
    store.decide_plan(task_id, "approve")
    claimed = store.claim_task("worker-1", "execution")
    assert claimed is not None


def test_run_execution_stops_when_target_project_deleted(monkeypatch):
    def _gone(pid):
        raise ValueError(f"Project '{pid}' no longer exists.")

    monkeypatch.setattr(planning, "validate_target_project", _gone)
    task = store.create_task("deleted target job")
    plan = _v3_coding_plan(task["task_id"])
    _ready_for_execution(task["task_id"])
    executor = FakeExecutor()
    task_worker._run_execution(task["task_id"], plan, executor)
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "waiting_reapproval"
    assert executor.calls == []
    plans = store.list_plans(task["task_id"])
    assert [p["version"] for p in plans] == [1, 2]
    assert plans[1]["status"] == "pending"


def test_run_execution_passes_when_target_project_valid(monkeypatch):
    monkeypatch.setattr(
        planning, "validate_target_project", lambda pid: ("Demo", "/repo/demo")
    )
    task = store.create_task("valid target job")
    plan = _v3_coding_plan(task["task_id"])
    _ready_for_execution(task["task_id"])

    def _scripted(task_id, plan_record, executor=None, action_generator=None, conn=None):
        return execution.ExecutorOutcome(kind="completed", result_summary="done")

    import obsidian_ai_hub.tasks.orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "run_directional_plan", _scripted)
    task_worker._run_execution(task["task_id"], plan, FakeExecutor())
    assert store.get_task(task["task_id"])["status"] == "completed"


def test_run_execution_ignores_target_for_non_coding_v3(monkeypatch):
    calls = []
    monkeypatch.setattr(
        planning,
        "validate_target_project",
        lambda pid: calls.append(pid) or ("Demo", "/repo/demo"),
    )
    task = store.create_task("non coding job")
    plan = store.create_plan(
        task["task_id"],
        {
            "plan_version": 3,
            "purpose": "調べる",
            "strategy": "検索",
            "capabilities": [{"capability_key": "web_search", "intent": "検索"}],
            "allowed_agent_ids": [],
            "allowed_project_ids": [],
            "project_resolution": {
                "kind": "general",
                "project_id": None,
                "display_name": "",
                "confidence": 0.9,
                "rationale": "一般作業",
                "source": "inferred",
            },
            "constraints": "",
            "completion_criteria": "done",
            "max_actions": 5,
        },
        {"web_search": "auto"},
    )
    assert task_worker._ensure_target_project_valid(task["task_id"], plan) is True
    assert calls == []
