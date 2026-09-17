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
