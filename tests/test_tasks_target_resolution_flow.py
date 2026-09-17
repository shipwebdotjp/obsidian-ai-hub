"""Vertical flow: low-confidence -> HITL answer -> plan -> approve -> single-project run.

Isolated DB + fake Coding Adapter (no external execution).
"""

import json

from obsidian_ai_hub.hitl.dispatcher import HitlContext
from obsidian_ai_hub.tasks import execution, planning, store
from obsidian_ai_hub.tasks import worker as task_worker
from obsidian_ai_hub.tasks.hitl import resolve_task_target


def _flow_context():
    return {
        "capabilities": [
            {
                "capability_key": "coding_cli",
                "adapter_kind": "coding",
                "approval_policy": "plan_required",
            }
        ],
        "agents": [],
        "projects": [
            {
                "project_id": 7,
                "name": "Demo Seven",
                "keywords": ["demo"],
                "git_root": "/repo/demo",
            }
        ],
    }


def _low_confidence_plan():
    return json.dumps(
        {
            "type": "plan",
            "purpose": "Demo Sevenを実装する",
            "strategy": "codingする",
            "capabilities": [
                {"capability_key": "coding_cli", "intent": "対象Projectで実装"}
            ],
            "constraints": "",
            "completion_criteria": "done",
            "max_actions": 5,
            "project_resolution": {
                "kind": "project",
                "project_id": 7,
                "display_name": "Demo Seven",
                "confidence": 0.2,
                "rationale": "依頼文が曖昧",
                "source": "inferred",
            },
        },
        ensure_ascii=False,
    )


class _CodingExecutor:
    def __init__(self):
        self.calls = []

    def execute_step(self, task, plan, step_index, step):
        self.calls.append(
            (
                step_index,
                step["capability_key"],
                dict(step.get("target") or {}),
            )
        )
        return execution.StepResult(
            step_index=step_index,
            capability_key=step["capability_key"],
            summary="implemented",
        )


def _stub_valid_project(monkeypatch):
    from obsidian_ai_hub.coding import backend as coding_backend
    from obsidian_ai_hub.web.services import projects as project_service

    monkeypatch.setattr(
        project_service,
        "get_project_detail",
        lambda pid: (
            {
                "project_id": 7,
                "display_name": "Demo Seven",
                "normalized_name": "demo seven",
                "project_path": "/repo/demo",
            }
            if pid == 7
            else None
        ),
    )
    monkeypatch.setattr(coding_backend, "validate_git_repo", lambda path: "/repo/demo")


def test_low_confidence_to_hitl_answer_to_single_project_run(monkeypatch):
    import obsidian_ai_hub.tasks.orchestrator as orchestrator_module

    _stub_valid_project(monkeypatch)
    store.sync_capabilities()
    monkeypatch.setattr(planning, "collect_planner_context", _flow_context)
    monkeypatch.setattr(
        planning, "generate_llm_response", lambda *a, **k: _low_confidence_plan()
    )

    task = store.create_task("Demo Sevenを実装して")
    task_id = task["task_id"]

    # 1. Low confidence -> no plan saved, HITL question instead.
    assert store.claim_task("worker-1", "planning") is not None
    result = planning.plan_task(task_id)
    assert result["outcome"] == "waiting_user"
    assert store.list_plans(task_id) == []
    assert result["hitl_run_id"]

    # 2. Human answers "project:7" -> selection persisted, task requeued.
    ctx = HitlContext(
        run_id=result["hitl_run_id"],
        checkpoint=json.dumps({"task_id": task_id}),
        answers_by_question_key={"target": "project:7"},
        conn=None,
        raw_answers_by_question_key={"target": "project:7"},
    )
    answer_result = resolve_task_target(ctx)
    assert answer_result.status == "completed"
    assert store.get_task(task_id)["status"] == "queued"

    # 3. Replan on the forced selection -> v3 plan awaiting approval.
    assert store.claim_task("worker-1", "planning") is not None
    result = planning.plan_task(task_id)
    assert result["outcome"] == "waiting_approval"
    plan_inner = result["plan"]["plan"]
    assert plan_inner["plan_version"] == 3
    resolution = plan_inner["project_resolution"]
    assert resolution["kind"] == "project"
    assert resolution["project_id"] == 7
    assert resolution["source"] == "user"
    assert plan_inner["allowed_project_ids"] == [7]

    # 4. Approve and run: only the selected project executes, exactly once.
    store.decide_plan(task_id, "approve")
    claimed = store.claim_task("worker-1", "execution")
    assert claimed is not None
    actions = [
        {
            "action": "call_capability",
            "capability_key": "coding_cli",
            "target": {"project_id": 7},
            "inputs": {"task": "implement"},
            "reason": "対象Projectで実行",
        },
        {"action": "finish", "summary": "実装した", "reason": "完了"},
    ]
    queue = list(actions)
    monkeypatch.setattr(
        orchestrator_module,
        "_default_generator",
        lambda task_id_arg, index: (lambda prompt: queue.pop(0)),
    )
    executor = _CodingExecutor()
    plan = store.get_plan(str(claimed["current_plan_id"]))
    assert plan is not None
    task_worker._run_execution(task_id, plan, executor)
    assert executor.calls == [(0, "coding_cli", {"project_id": 7})]
    updated = store.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "completed"
