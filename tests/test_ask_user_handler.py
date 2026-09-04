import json

from obsidian_ai_hub.hitl.dispatcher import HitlContext, HitlResult
from obsidian_ai_hub.agents.ask_user_handler import handle_agent_ask_user, handle_coding_ask_user

def test_handle_agent_ask_user_formatting(monkeypatch):
    updated = {}
    def mock_update_run_hitl(**kwargs):
        updated.update(kwargs)

    monkeypatch.setattr("obsidian_ai_hub.agents.store.update_run_hitl", mock_update_run_hitl)
    cp = {
        "domain": "agent",
        "run_id": "arun_123",
        "tool_call_id": "call_456"
    }
    ctx = HitlContext(
        run_id="hitl_123",
        checkpoint=json.dumps(cp),
        answers_by_question_key={"q1": "opt1", "q2": "other"},
        conn=None,
        raw_answers_by_question_key={
            "q1": {"value": "opt1", "comment": None},
            "q2": {"value": "other", "comment": "Custom details"}
        }
    )
    res = handle_agent_ask_user(ctx)
    assert isinstance(res, HitlResult)
    assert res.status == "completed"
    assert updated == {"run_id": "arun_123", "status": "queued", "hitl_run_id": "hitl_123"}
    persisted = json.loads(res.checkpoint)
    assert persisted["answers"]["q1"] == {"selection": "opt1", "text": None}
    assert persisted["answers"]["q2"] == {"selection": "other", "text": "Custom details"}

def test_handle_coding_ask_user_formatting(monkeypatch):
    updated = {}
    def mock_update_run(**kwargs):
        updated.update(kwargs)

    monkeypatch.setattr("obsidian_ai_hub.coding.store.update_run", mock_update_run)
    cp = {
        "domain": "coding",
        "run_id": "crun_123",
        "tool_call_id": "call_789"
    }
    ctx = HitlContext(
        run_id="hitl_456",
        checkpoint=json.dumps(cp),
        answers_by_question_key={"q1": "opt2"},
        conn=None,
        raw_answers_by_question_key={
            "q1": {"value": "opt2", "comment": None}
        }
    )
    res = handle_coding_ask_user(ctx)
    assert isinstance(res, HitlResult)
    assert res.status == "completed"
    assert updated == {"run_id": "crun_123", "status": "queued", "hitl_run_id": "hitl_456"}
    persisted = json.loads(res.checkpoint)
    assert persisted["answers"]["q1"] == {"selection": "opt2", "text": None}
