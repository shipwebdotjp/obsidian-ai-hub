import json

import pytest

from obsidian_ai_hub.hitl.dispatcher import HitlContext
from obsidian_ai_hub.tasks import intake, store
from obsidian_ai_hub.tasks.hitl import resolve_task_target
from obsidian_ai_hub.utils import config


def test_submit_request_builds_receipt(monkeypatch):
    monkeypatch.setattr(config, "OBSIDIAN_AI_HUB_WEB_URL", "https://example.test")
    receipt = intake.submit_request("do the thing")
    assert receipt["status"] == "queued"
    assert (
        receipt["detail_url"] == f"https://example.test/task-agent/{receipt['task_id']}"
    )
    assert store.get_task(receipt["task_id"]) is not None


def test_submit_request_falls_back_to_host_port(monkeypatch):
    monkeypatch.setattr(config, "OBSIDIAN_AI_HUB_WEB_URL", "")
    receipt = intake.submit_request("do the thing", host="127.0.0.1", port=9999)
    assert (
        receipt["detail_url"]
        == f"http://127.0.0.1:9999/task-agent/{receipt['task_id']}"
    )


def test_submit_request_rejects_blank():
    with pytest.raises(ValueError, match="must not be blank"):
        intake.submit_request("   ")


def _context(task_id, answer="proj_a"):
    return HitlContext(
        run_id=f"tasks_{task_id}_abc",
        checkpoint=json.dumps({"task_id": task_id}),
        answers_by_question_key={"target": answer},
        conn=None,
        raw_answers_by_question_key={"target": answer},
    )


def test_resolve_task_target_requeues():
    task = store.create_task("ambiguous job")
    store.claim_task("worker-test", "planning")
    store.transition_task_status(task["task_id"], "waiting_user")
    result = resolve_task_target(_context(task["task_id"]))
    assert result.status == "completed"
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "queued"
    events = store.list_task_events(task["task_id"])
    assert [e["event_type"] for e in events] == ["hitl_question_answered"]
    assert events[0]["payload"]["answer"] == "proj_a"


def test_resolve_task_target_preserves_comment():
    task = store.create_task("ambiguous job")
    store.claim_task("worker-test", "planning")
    store.transition_task_status(task["task_id"], "waiting_user")
    ctx = HitlContext(
        run_id=f"tasks_{task['task_id']}_abc",
        checkpoint=json.dumps({"task_id": task["task_id"]}),
        answers_by_question_key={"target": "agent:agent_1"},
        conn=None,
        raw_answers_by_question_key={
            "target": {"value": "agent:agent_1", "comment": "use the runtime"}
        },
    )
    result = resolve_task_target(ctx)
    assert result.status == "completed"
    events = store.list_task_events(task["task_id"])
    answered = [e for e in events if e["event_type"] == "hitl_question_answered"]
    assert len(answered) == 1
    assert answered[0]["payload"]["answer"] == "agent:agent_1"
    assert answered[0]["payload"]["comment"] == "use the runtime"


def test_resolve_task_target_bad_checkpoint_completes():
    ctx = HitlContext(
        run_id="tasks_broken",
        checkpoint="not-json",
        answers_by_question_key={},
        conn=None,
        raw_answers_by_question_key={},
    )
    result = resolve_task_target(ctx)
    assert result.status == "completed"


def _stub_valid_project(monkeypatch, project_id=7):
    from obsidian_ai_hub.coding import backend as coding_backend
    from obsidian_ai_hub.web.services import projects as project_service

    monkeypatch.setattr(
        project_service,
        "list_projects",
        lambda *a, **k: [
            {
                "project_id": project_id,
                "display_name": "Demo Seven",
                "normalized_name": "demo seven",
                "keywords": [],
                "project_path": "/repo/demo",
            }
        ],
    )
    monkeypatch.setattr(
        project_service,
        "get_project_detail",
        lambda pid: (
            {
                "project_id": project_id,
                "display_name": "Demo Seven",
                "normalized_name": "demo seven",
                "project_path": "/repo/demo",
            }
            if pid == project_id
            else None
        ),
    )
    monkeypatch.setattr(coding_backend, "validate_git_repo", lambda path: "/repo/demo")


def test_resolve_task_target_records_project_selection(monkeypatch):
    _stub_valid_project(monkeypatch)
    task = store.create_task("selection job")
    store.claim_task("worker-test", "planning")
    store.transition_task_status(task["task_id"], "waiting_user")
    ctx = HitlContext(
        run_id=f"tasks_{task['task_id']}_abc",
        checkpoint=json.dumps({"task_id": task["task_id"]}),
        answers_by_question_key={"target": "project:7"},
        conn=None,
        raw_answers_by_question_key={"target": "project:7"},
    )
    result = resolve_task_target(ctx)
    assert result.status == "completed"
    assert store.get_task(task["task_id"])["status"] == "queued"
    events = store.list_task_events(task["task_id"])
    assert [e["event_type"] for e in events] == [
        "target_resolution_selected",
        "hitl_question_answered",
    ]
    assert events[0]["payload"]["project_id"] == 7
    assert events[0]["payload"]["kind"] == "project"


def test_resolve_task_target_records_general_selection():
    task = store.create_task("general job")
    store.claim_task("worker-test", "planning")
    store.transition_task_status(task["task_id"], "waiting_user")
    ctx = HitlContext(
        run_id=f"tasks_{task['task_id']}_abc",
        checkpoint=json.dumps({"task_id": task["task_id"]}),
        answers_by_question_key={"target": "general"},
        conn=None,
        raw_answers_by_question_key={"target": "general"},
    )
    result = resolve_task_target(ctx)
    assert result.status == "completed"
    events = store.list_task_events(task["task_id"])
    assert [e["event_type"] for e in events] == [
        "target_resolution_selected",
        "hitl_question_answered",
    ]
    assert events[0]["payload"]["kind"] == "general"


def test_resolve_task_target_resuspends_on_deleted_project(monkeypatch):
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub.hitl.service import register_run_and_questions
    from obsidian_ai_hub.hitl.store import get_questions_by_set

    _stub_valid_project(monkeypatch)
    task = store.create_task("deleted selection job")
    store.claim_task("worker-test", "planning")
    store.transition_task_status(task["task_id"], "waiting_user")
    hitl_run_id = f"tasks_{task['task_id']}_sel"
    register_run_and_questions(
        run_id=hitl_run_id,
        handler="tasks.resolve_target",
        checkpoint=json.dumps({"task_id": task["task_id"]}),
        question_set_id="target",
        questions_data=[
            {
                "question_key": "target",
                "question_type": "select",
                "display_text": "Which repo?",
                "title": "Taskの対象確認",
                "prompt": "Which repo?",
                "choices": [
                    {"value": "project:99", "label": "Gone"},
                    {"value": "general", "label": "General"},
                ],
                "is_required": 1,
            }
        ],
        title="Taskの対象確認",
        description="ambiguous job",
        display_type="task_target_question",
    )
    conn = get_db_connection()
    try:
        ctx = HitlContext(
            run_id=hitl_run_id,
            checkpoint=json.dumps({"task_id": task["task_id"]}),
            answers_by_question_key={"target": "project:99"},
            conn=conn,
            raw_answers_by_question_key={"target": "project:99"},
        )
        result = resolve_task_target(ctx)
    finally:
        conn.close()
    assert result.status == "re_suspended"
    # The task stays waiting: no selection persisted, no requeue.
    events = store.list_task_events(task["task_id"])
    assert events == []
    assert store.get_task(task["task_id"])["status"] == "waiting_user"
    retry = get_questions_by_set(hitl_run_id, "target_retry")
    assert len(retry) == 1
    values = [c["value"] for c in retry[0]["choices"]]
    assert "project:7" in values
    assert "general" in values
