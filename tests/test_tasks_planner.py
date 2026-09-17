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


def test_valid_projects_uses_display_name_and_keywords(monkeypatch):
    from obsidian_ai_hub.coding import backend as coding_backend
    from obsidian_ai_hub.web.services import projects as project_service

    monkeypatch.setattr(
        project_service,
        "list_projects",
        lambda: [
            {
                "project_id": 1,
                "normalized_name": "obsidian ai hub",
                "display_name": "Obsidian AI Hub",
                "keywords": ["obsidian-ai-hub", "React"],
                "project_path": "/repo/demo",
            },
            {
                "project_id": 2,
                "normalized_name": "no path",
                "display_name": "",
                "keywords": [],
                "project_path": "",
            },
        ],
    )
    monkeypatch.setattr(coding_backend, "validate_git_repo", lambda path: "/repo/demo")
    # _valid_projects imports both lazily; attribute patches apply.
    projects = planning._valid_projects()
    assert projects == [
        {
            "project_id": 1,
            "name": "Obsidian AI Hub",
            "keywords": ["obsidian-ai-hub", "React"],
            "git_root": "/repo/demo",
        }
    ]


def test_build_planner_prompt_shows_project_names_and_keywords():
    context = dict(
        _context(),
        projects=[
            {
                "project_id": 1,
                "name": "Obsidian AI Hub",
                "keywords": ["obsidian-ai-hub"],
                "git_root": "/repo/demo",
            }
        ],
    )
    prompt = planning.build_planner_prompt("do it", context, [])
    assert "- 1: Obsidian AI Hub (/repo/demo)" in prompt
    assert "obsidian-ai-hub" in prompt


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


def _directional_json(**overrides):
    plan = {
        "type": "plan",
        "purpose": "好みを記憶する",
        "strategy": "検索して提案",
        "capabilities": [
            {"capability_key": "web_search", "intent": "検索する"},
        ],
        "constraints": "",
        "completion_criteria": "done",
        "max_actions": 5,
    }
    plan.update(overrides)
    return json.dumps(plan, ensure_ascii=False)


def test_parse_planner_output_directional():
    plan = planning.parse_planner_output(_directional_json())
    assert plan["plan_version"] == 2
    assert plan["capabilities"][0]["capability_key"] == "web_search"
    assert "steps" not in plan

    with pytest.raises(ValueError, match="capabilities"):
        planning.parse_planner_output(
            json.dumps({"type": "plan", "purpose": "p", "completion_criteria": "d"})
        )
    with pytest.raises(ValueError, match="blank"):
        planning.parse_planner_output(_directional_json(purpose="  "))
    with pytest.raises(ValueError, match="must not be empty"):
        planning.parse_planner_output(_directional_json(capabilities=[]))


def test_validate_directional_plan():
    plan = json.loads(_directional_json())
    snapshot = planning.validate_directional_plan(plan, _context())
    assert snapshot == {"web_search": "auto"}

    bad = json.loads(_directional_json())
    bad["capabilities"][0]["capability_key"] = "run_shell"
    with pytest.raises(ValueError, match="unknown or disabled"):
        planning.validate_directional_plan(bad, _context())

    dup = json.loads(_directional_json())
    dup["capabilities"].append({"capability_key": "web_search", "intent": "x"})
    with pytest.raises(ValueError, match="twice"):
        planning.validate_directional_plan(dup, _context())


def test_validate_directional_rejects_unresolvable_schema(monkeypatch):
    from obsidian_ai_hub.tasks import capability_schemas

    monkeypatch.setattr(capability_schemas, "resolve_json_schema", lambda key: None)
    with pytest.raises(ValueError, match="no resolvable input schema"):
        planning.validate_directional_plan(json.loads(_directional_json()), _context())


def test_plan_task_directional_saves_scope(monkeypatch):
    monkeypatch.setattr(planning, "collect_planner_context", _context)
    monkeypatch.setattr(
        planning, "generate_llm_response", lambda *a, **k: _directional_json()
    )
    task = store.create_task("directional job")
    _claim(task["task_id"])
    result = planning.plan_task(task["task_id"])
    assert result["outcome"] == "running"
    plan_inner = result["plan"]["plan"]
    assert plan_inner["plan_version"] == 2
    assert plan_inner["capabilities"][0]["capability_key"] == "web_search"
    assert "steps" not in plan_inner
    assert result["plan"]["approval_policy_snapshot"] == {"web_search": "auto"}


def test_plan_task_directional_plan_required_waits_approval(monkeypatch):
    context = dict(
        _context(),
        capabilities=_context()["capabilities"]
        + [
            {
                "capability_key": "memory_propose",
                "adapter_kind": "memory",
                "approval_policy": "plan_required",
            }
        ],
    )
    monkeypatch.setattr(planning, "collect_planner_context", lambda: context)
    raw = _directional_json(
        capabilities=[{"capability_key": "memory_propose", "intent": "記憶する"}]
    )
    monkeypatch.setattr(planning, "generate_llm_response", lambda *a, **k: raw)
    task = store.create_task("memory job")
    _claim(task["task_id"])
    result = planning.plan_task(task["task_id"])
    assert result["outcome"] == "waiting_approval"
    assert result["plan"]["plan"]["max_actions"] == 5


def test_validate_directional_stamps_target_allowlists():
    context = dict(
        _context(),
        agents=[{"agent_id": "agent_1", "name": "Helper"}],
        projects=[{"project_id": 3, "name": "Demo", "git_root": "/repo/demo"}],
    )
    plan = json.loads(
        _directional_json(
            capabilities=[
                {"capability_key": "web_search", "intent": "検索"},
                {"capability_key": "specialist_agent", "intent": "委譲"},
                {"capability_key": "coding_cli", "intent": "実装"},
            ]
        )
    )
    context["capabilities"] = context["capabilities"] + [
        {
            "capability_key": "specialist_agent",
            "adapter_kind": "agent",
            "approval_policy": "plan_required",
        },
        {
            "capability_key": "coding_cli",
            "adapter_kind": "coding",
            "approval_policy": "plan_required",
        },
    ]
    snapshot = planning.validate_directional_plan(plan, context)
    assert set(snapshot) == {"web_search", "specialist_agent", "coding_cli"}
    assert plan["allowed_agent_ids"] == ["agent_1"]
    assert plan["allowed_project_ids"] == [3]


def test_validate_directional_rejects_delegate_without_registry():
    plan = json.loads(
        _directional_json(
            capabilities=[{"capability_key": "specialist_agent", "intent": "委譲"}]
        )
    )
    context = dict(
        _context(),
        agents=[],
        capabilities=_context()["capabilities"]
        + [
            {
                "capability_key": "specialist_agent",
                "adapter_kind": "agent",
                "approval_policy": "plan_required",
            }
        ],
    )
    with pytest.raises(ValueError, match="no agents are registered"):
        planning.validate_directional_plan(plan, context)

    coding_plan = json.loads(
        _directional_json(
            capabilities=[{"capability_key": "coding_cli", "intent": "実装"}]
        )
    )
    coding_context = dict(
        _context(),
        projects=[],
        capabilities=_context()["capabilities"]
        + [
            {
                "capability_key": "coding_cli",
                "adapter_kind": "coding",
                "approval_policy": "plan_required",
            }
        ],
    )
    with pytest.raises(ValueError, match="no valid projects"):
        planning.validate_directional_plan(coding_plan, coding_context)


def _seed_rejected_plan(task_id, purpose, reason, capabilities=("coding_cli",)):
    plan_inner = {
        "plan_version": 2,
        "purpose": purpose,
        "strategy": "",
        "capabilities": [
            {"capability_key": key, "intent": "test"} for key in capabilities
        ],
        "allowed_agent_ids": [],
        "allowed_project_ids": [],
        "agent_config_snapshot": {},
        "constraints": "",
        "completion_criteria": "done",
        "max_actions": 8,
    }
    store.create_plan(task_id, plan_inner, {"coding_cli": "plan_required"})
    current = store.get_task(task_id)
    if current["status"] == "planning":
        store.transition_task_status(task_id, "waiting_approval")
    store.decide_plan(task_id, "reject", reason=reason)
    return store.list_plans(task_id)[-1]


def test_get_task_rejection_history_returns_rejected_newest_first():
    task = store.create_task("rejected job")
    _claim(task["task_id"])
    _seed_rejected_plan(task["task_id"], "first purpose", "first reason")
    store.claim_task("worker-test", "planning")
    _seed_rejected_plan(task["task_id"], "second purpose", "second reason")
    history = planning.get_task_rejection_history(task["task_id"])
    assert [h["version"] for h in history] == [2, 1]
    assert history[0]["reason"] == "second reason"
    assert history[0]["purpose"] == "second purpose"
    assert history[0]["capabilities"] == ["coding_cli"]


def test_get_task_rejection_history_empty_without_rejections():
    task = store.create_task("fresh job")
    assert planning.get_task_rejection_history(task["task_id"]) == []


def test_build_planner_prompt_includes_rejection_history():
    prompt = planning.build_planner_prompt(
        "do it",
        _context(),
        [],
        [
            {
                "plan_id": "tplan_x",
                "version": 1,
                "reason": "delegate to runtime instead",
                "purpose": "old purpose",
                "capabilities": ["coding_cli"],
            }
        ],
    )
    assert "delegate to runtime instead" in prompt
    assert "old purpose" in prompt
    assert "coding_cli" in prompt

    without = planning.build_planner_prompt("do it", _context(), [], [])
    assert "却下" not in without


def test_build_planner_prompt_includes_qa_comment():
    prompt = planning.build_planner_prompt(
        "do it",
        _context(),
        [
            {
                "hitl_run_id": "tasks_x_1",
                "question": "Which agent?",
                "answer": "agent:agent_1",
                "comment": "use the runtime orchestrator",
            }
        ],
    )
    assert "use the runtime orchestrator" in prompt


def test_get_task_qa_history_includes_comment():
    task = store.create_task("ambiguous job")
    hitl_run_id = _seed_qa_round(task["task_id"])
    store.append_task_event(
        task["task_id"],
        "hitl_question_asked",
        {"hitl_run_id": "other-run", "question_set_id": "target"},
    )
    store.append_task_event(
        task["task_id"],
        "hitl_question_answered",
        {
            "hitl_run_id": "other-run",
            "answer": "agent:agent_1",
            "comment": "use the runtime orchestrator",
        },
    )
    history = planning.get_task_qa_history(task["task_id"])
    assert history[0]["comment"] is None
    assert history[0]["hitl_run_id"] == hitl_run_id
    commented = [h for h in history if h["hitl_run_id"] == "other-run"][0]
    assert commented["comment"] == "use the runtime orchestrator"


def test_plan_task_includes_rejection_reason_in_prompt(monkeypatch):
    monkeypatch.setattr(planning, "collect_planner_context", _context)
    seen = {}

    def fake_llm(provider, model, prompt, **kwargs):
        seen["prompt"] = prompt
        return _plan_json()

    monkeypatch.setattr(planning, "generate_llm_response", fake_llm)
    task = store.create_task("replanned job")
    _claim(task["task_id"])
    _seed_rejected_plan(
        task["task_id"], "delegate to project agent", "use the runtime instead"
    )
    store.claim_task("worker-test", "planning")
    result = planning.plan_task(task["task_id"])
    assert result["outcome"] == "running"
    assert "use the runtime instead" in seen["prompt"]
    assert "delegate to project agent" in seen["prompt"]


def test_plan_task_directional_records_allowlist_snapshot(monkeypatch):
    context = dict(
        _context(),
        agents=[{"agent_id": "agent_9", "name": "Nine"}],
        projects=[{"project_id": 7, "name": "P", "git_root": "/repo/p"}],
    )
    monkeypatch.setattr(planning, "collect_planner_context", lambda: context)
    monkeypatch.setattr(
        planning, "generate_llm_response", lambda *a, **k: _directional_json()
    )
    task = store.create_task("allowlist job")
    _claim(task["task_id"])
    result = planning.plan_task(task["task_id"])
    assert result["outcome"] == "running"
    saved = result["plan"]["plan"]
    assert saved["allowed_agent_ids"] == ["agent_9"]
    assert saved["allowed_project_ids"] == [7]
