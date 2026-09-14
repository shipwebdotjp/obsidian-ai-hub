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


def test_validate_plan_targets_accepts_string_project_id():
    context = dict(
        _context(),
        projects=[{"project_id": 1, "name": "Demo", "git_root": "/repo/demo"}],
    )
    plan = json.loads(_plan_json())
    plan["steps"][0]["capability_key"] = "coding_cli"
    plan["steps"][0]["target"] = {"project_id": "1"}
    snapshot = planning.validate_plan_targets(plan, context)
    assert snapshot == {"coding_cli": "plan_required"}
    assert plan["steps"][0]["target"]["project_id"] == 1

    bad = json.loads(_plan_json())
    bad["steps"][0]["capability_key"] = "coding_cli"
    bad["steps"][0]["target"] = {"project_id": "not-a-project"}
    with pytest.raises(ValueError, match="invalid project"):
        planning.validate_plan_targets(bad, context)


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


def test_question_options_shape():
    question = planning.parse_planner_output(
        json.dumps(
            {
                "type": "question",
                "question_text": "Which repo?",
                "options": [
                    {"value": "project:1", "label": "Project 1"},
                    {"value": "other", "label": "Other"},
                ],
            }
        )
    )
    assert question["options"] == [
        {"value": "project:1", "label": "Project 1"},
        {"value": "other", "label": "Other"},
    ]

    legacy = planning.parse_planner_output(
        json.dumps(
            {"type": "question", "question_text": "Which repo?", "choices": ["a"]}
        )
    )
    assert legacy["options"] == [{"value": "a", "label": "a"}]

    no_options = planning.parse_planner_output(
        json.dumps({"type": "question", "question_text": "Which repo?"})
    )
    assert no_options["options"] == []

    with pytest.raises(ValueError, match="non-empty list"):
        planning.parse_planner_output(
            json.dumps({"type": "question", "question_text": "Q?", "options": []})
        )
    with pytest.raises(ValueError, match="non-blank value"):
        planning.parse_planner_output(
            json.dumps(
                {
                    "type": "question",
                    "question_text": "Q?",
                    "options": [{"value": " ", "label": "x"}],
                }
            )
        )
    with pytest.raises(ValueError, match="non-blank label"):
        planning.parse_planner_output(
            json.dumps(
                {
                    "type": "question",
                    "question_text": "Q?",
                    "options": [{"value": "x", "label": " "}],
                }
            )
        )


def test_question_options_register_value_label(monkeypatch):
    from obsidian_ai_hub.hitl import store as hitl_store

    monkeypatch.setattr(planning, "collect_planner_context", _context)
    monkeypatch.setattr(
        planning,
        "generate_llm_response",
        lambda *a, **k: json.dumps(
            {
                "type": "question",
                "question_text": "Which repo?",
                "options": [{"value": "project:1", "label": "Project 1: Demo"}],
            }
        ),
    )
    task = store.create_task("ambiguous job")
    _claim(task["task_id"])
    result = planning.plan_task(task["task_id"])
    assert result["outcome"] == "waiting_user"
    questions = hitl_store.get_questions_by_set(result["hitl_run_id"], "target")
    assert len(questions) == 1
    assert questions[0]["choices"] == [
        {"value": "project:1", "label": "Project 1: Demo"}
    ]


def _seed_qa_round(task_id):
    """Register one answered target question round via the real planner path."""
    from obsidian_ai_hub.hitl.service import register_run_and_questions

    hitl_run_id = f"tasks_{task_id}_seed1"
    register_run_and_questions(
        run_id=hitl_run_id,
        handler=planning.TASK_RESOLVE_HANDLER,
        checkpoint=json.dumps({"task_id": task_id}),
        question_set_id="target",
        questions_data=[
            {
                "question_key": "target",
                "question_type": "select",
                "display_text": "Which repo?",
                "title": "Taskの対象確認",
                "prompt": "Which repo?",
                "choices": [{"value": "project:1", "label": "Project 1: Demo"}],
                "is_required": 1,
            }
        ],
        title="Taskの対象確認",
        description="ambiguous job",
        display_type="task_target_question",
    )
    store.append_task_event(
        task_id,
        "hitl_question_asked",
        {"hitl_run_id": hitl_run_id, "question_set_id": "target"},
    )
    store.append_task_event(
        task_id,
        "hitl_question_answered",
        {"hitl_run_id": hitl_run_id, "answer": "project:1"},
    )
    return hitl_run_id


def test_get_task_qa_history_pairs_question_answer():
    task = store.create_task("ambiguous job")
    hitl_run_id = _seed_qa_round(task["task_id"])
    history = planning.get_task_qa_history(task["task_id"])
    assert len(history) == 1
    assert history[0]["hitl_run_id"] == hitl_run_id
    assert history[0]["question"] == "Which repo?"
    assert history[0]["answer"] == "project:1"


def test_build_planner_prompt_includes_qa_history():
    prompt = planning.build_planner_prompt(
        "do it",
        _context(),
        [
            {
                "hitl_run_id": "tasks_x_1",
                "question": "Which repo?",
                "answer": "project:1",
            },
            {"hitl_run_id": "tasks_x_2", "question": "Which agent?", "answer": None},
        ],
    )
    assert "以前の質問と回答" in prompt
    assert "Which repo?" in prompt
    assert "project:1" in prompt
    assert "未回答" in prompt

    without = planning.build_planner_prompt("do it", _context(), [])
    assert "以前の質問と回答" not in without


def test_plan_task_after_answer_builds_plan(monkeypatch):
    monkeypatch.setattr(planning, "collect_planner_context", _context)
    seen = {}

    def fake_llm(provider, model, prompt, **kwargs):
        seen["prompt"] = prompt
        return _plan_json()

    monkeypatch.setattr(planning, "generate_llm_response", fake_llm)
    task = store.create_task("ambiguous job")
    _claim(task["task_id"])
    # Simulate: question asked on the first planning round, answered, re-queued.
    store.append_task_event(
        task["task_id"],
        "hitl_question_asked",
        {"hitl_run_id": "tasks_old", "question_set_id": "target"},
    )
    store.append_task_event(
        task["task_id"],
        "hitl_question_answered",
        {"hitl_run_id": "tasks_old", "answer": "project:1"},
    )
    result = planning.plan_task(task["task_id"])
    assert result["outcome"] == "running"
    assert "project:1" in seen["prompt"]
