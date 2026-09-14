import json

import pytest

from obsidian_ai_hub.hitl.store import get_run as get_hitl_run
from obsidian_ai_hub.tasks import planning, store


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
        "agents": [{"agent_id": "agent_1", "name": "Helper"}],
        "projects": [
            {"project_id": "proj_1", "name": "Demo", "git_root": "/repo/demo"}
        ],
    }


def _plan_json(**overrides):
    plan = {
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
    plan.update(overrides)
    return json.dumps(plan, ensure_ascii=False)


def test_parse_planner_output_plan_and_question():
    plan = planning.parse_planner_output(_plan_json())
    assert plan["type"] == "plan"
    assert plan["steps"][0]["capability_key"] == "web_search"

    fenced = "```json\n" + _plan_json() + "\n```"
    assert planning.parse_planner_output(fenced)["type"] == "plan"

    question = planning.parse_planner_output(
        json.dumps(
            {"type": "question", "question_text": "Which repo?", "choices": ["a", "b"]}
        )
    )
    assert question["choices"] == ["a", "b"]

    with pytest.raises(ValueError, match="not valid JSON"):
        planning.parse_planner_output("not json")
    with pytest.raises(ValueError, match="unknown type"):
        planning.parse_planner_output(json.dumps({"type": "other"}))
    with pytest.raises(ValueError, match="purpose"):
        planning.parse_planner_output(_plan_json(purpose="  "))
    with pytest.raises(ValueError, match="non-empty steps"):
        planning.parse_planner_output(_plan_json(steps=[]))
    with pytest.raises(ValueError, match="question_text"):
        planning.parse_planner_output(json.dumps({"type": "question"}))


def test_validate_plan_targets():
    context = _context()
    plan = json.loads(_plan_json())
    snapshot = planning.validate_plan_targets(plan, context)
    assert snapshot == {"web_search": "auto"}

    bad_cap = json.loads(_plan_json())
    bad_cap["steps"][0]["capability_key"] = "run_shell"
    with pytest.raises(ValueError, match="unknown or disabled"):
        planning.validate_plan_targets(bad_cap, context)

    agent_plan = json.loads(_plan_json())
    agent_plan["steps"][0]["capability_key"] = "specialist_agent"
    agent_plan["steps"][0]["target"] = {"agent_id": "agent_missing"}
    context_with_agent = dict(
        context,
        capabilities=context["capabilities"]
        + [
            {
                "capability_key": "specialist_agent",
                "adapter_kind": "agent",
                "approval_policy": "plan_required",
            }
        ],
    )
    with pytest.raises(ValueError, match="unregistered agent"):
        planning.validate_plan_targets(agent_plan, context_with_agent)

    coding_plan = json.loads(_plan_json())
    coding_plan["steps"][0]["capability_key"] = "coding_cli"
    coding_plan["steps"][0]["target"] = {"project_id": "proj_missing"}
    with pytest.raises(ValueError, match="invalid project"):
        planning.validate_plan_targets(coding_plan, context)


def _claim(task_id):
    claimed = store.claim_task("worker-test", "planning")
    assert claimed is not None
    assert claimed["task_id"] == task_id
    return claimed


def test_plan_task_auto_only_runs(monkeypatch):
    monkeypatch.setattr(planning, "collect_planner_context", _context)
    monkeypatch.setattr(planning, "generate_llm_response", lambda *a, **k: _plan_json())
    task = store.create_task("auto job")
    _claim(task["task_id"])
    result = planning.plan_task(task["task_id"])
    assert result["outcome"] == "running"
    assert result["task"]["status"] == "running"
    assert result["plan"]["version"] == 1
    events = store.list_task_events(task["task_id"])
    assert [e["event_type"] for e in events] == ["plan_created"]


def test_plan_task_plan_required_waits_approval(monkeypatch):
    monkeypatch.setattr(planning, "collect_planner_context", _context)
    plan = json.loads(_plan_json())
    plan["steps"][0]["capability_key"] = "coding_cli"
    plan["steps"][0]["target"] = {"project_id": "proj_1"}
    monkeypatch.setattr(
        planning, "generate_llm_response", lambda *a, **k: json.dumps(plan)
    )
    task = store.create_task("coding job")
    _claim(task["task_id"])
    result = planning.plan_task(task["task_id"])
    assert result["outcome"] == "waiting_approval"
    assert result["plan"]["approval_policy_snapshot"] == {"coding_cli": "plan_required"}


def test_plan_task_question_registers_hitl(monkeypatch):
    monkeypatch.setattr(planning, "collect_planner_context", _context)
    monkeypatch.setattr(
        planning,
        "generate_llm_response",
        lambda *a, **k: json.dumps(
            {"type": "question", "question_text": "Which repo?", "choices": ["a", "b"]}
        ),
    )
    task = store.create_task("ambiguous job")
    _claim(task["task_id"])
    result = planning.plan_task(task["task_id"])
    assert result["outcome"] == "waiting_user"
    hitl_run = get_hitl_run(result["hitl_run_id"])
    assert hitl_run is not None
    assert hitl_run["handler"] == planning.TASK_RESOLVE_HANDLER
    assert json.loads(hitl_run["checkpoint"])["task_id"] == task["task_id"]
    events = store.list_task_events(task["task_id"])
    assert [e["event_type"] for e in events] == ["hitl_question_asked"]


def test_plan_task_invalid_output_fails_immediately(monkeypatch):
    monkeypatch.setattr(planning, "collect_planner_context", _context)
    monkeypatch.setattr(planning, "generate_llm_response", lambda *a, **k: "not json")
    task = store.create_task("broken job")
    _claim(task["task_id"])
    with pytest.raises(ValueError, match="Planner failed"):
        planning.plan_task(task["task_id"])
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_summary"]


def test_plan_task_unknown_capability_fails(monkeypatch):
    monkeypatch.setattr(planning, "collect_planner_context", _context)
    plan = json.loads(_plan_json())
    plan["steps"][0]["capability_key"] = "run_shell"
    monkeypatch.setattr(
        planning, "generate_llm_response", lambda *a, **k: json.dumps(plan)
    )
    task = store.create_task("shell job")
    _claim(task["task_id"])
    with pytest.raises(ValueError, match="Planner failed"):
        planning.plan_task(task["task_id"])
    assert store.get_task(task["task_id"])["status"] == "failed"


def test_default_provider_model_fallback(monkeypatch):
    monkeypatch.setattr(planning.config, "AGENT_PROVIDER", "", raising=False)
    monkeypatch.setattr(planning.config, "AGENT_MODEL", "", raising=False)
    provider, model = planning.default_provider_model()
    assert provider == "openai"
    assert model == "gpt-4o"
