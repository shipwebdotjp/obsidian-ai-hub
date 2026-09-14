"""Tests for Task child-session reuse, session titles, and observation fidelity.

Covers the task_bde93d76a598 incident: repeated coding_cli actions must
reuse the task's existing session by default, new sessions must carry a
content-aware title instead of the fixed ``Task <id> step <n>`` pattern,
and orchestrator prompts must preserve completion evidence (commit SHAs)
found at the tail of child observations.
"""

import obsidian_ai_hub.agents.store as agent_store
import obsidian_ai_hub.coding.store as coding_store
import obsidian_ai_hub.web.services.projects as projects_service
from obsidian_ai_hub.coding import backend as coding_backend
from obsidian_ai_hub.tasks import capability_schemas as schemas
from obsidian_ai_hub.tasks import orchestrator as orchestrator_module
from obsidian_ai_hub.tasks import store
from obsidian_ai_hub.tasks.adapters import child_runs
from obsidian_ai_hub.tasks.adapters.agent import AgentAdapter
from obsidian_ai_hub.tasks.adapters.coding import CodingAdapter


def _legacy_task_plan(task_id, capability_key, target, inputs):
    return store.create_plan(
        task_id,
        {
            "purpose": "カレンダー提案をCapability化する",
            "steps": [
                {
                    "capability_key": capability_key,
                    "title": "実装ステップ",
                    "target": target,
                    "inputs": inputs,
                    "side_effects": "none",
                }
            ],
            "completion_criteria": "テスト成功とコミット",
        },
        {capability_key: "plan_required"},
    )


# --- session title builder ---


def test_title_prefers_work_hint_and_truncates():
    step = {
        "capability_key": "coding_cli",
        "title": "実装ステップ",
        "inputs": {
            "task": "Obsidian AI Hubで除外処理を調査・修正してください。テストも実行。"
        },
        "target": {"project_id": 1},
    }
    title = child_runs.build_task_session_title("task_abc", 0, step, None)
    assert title != "Task task_abc step 0"
    assert len(title) <= child_runs.TASK_SESSION_TITLE_LIMIT
    assert "Obsidian" in title


def test_title_falls_back_through_step_title_and_purpose():
    no_hint = {
        "capability_key": "coding_cli",
        "title": "実装ステップ",
        "inputs": {},
        "target": {},
    }
    assert (
        child_runs.build_task_session_title("task_abc", 1, no_hint, None)
        == "実装ステップ"
    )
    blank = {
        "capability_key": "coding_cli",
        "title": "coding_cli",
        "inputs": {},
        "target": {},
    }
    plan = {"plan": {"purpose": "カレンダー提案をCapability化する"}}
    assert (
        child_runs.build_task_session_title("task_abc", 2, blank, plan)
        == "カレンダー提案をCapability化する"
    )
    assert (
        child_runs.build_task_session_title("task_abc", 3, blank, None)
        == "Task task_abc step 3"
    )


def test_legacy_task_title_detection():
    assert child_runs.is_task_generated_session_title("Task task_bde93d76a598 step 2")
    assert child_runs.is_task_generated_session_title("  Task task_x step 0  ")
    assert not child_runs.is_task_generated_session_title(
        "Capability入力スキーマ二重定義の調査"
    )
    assert not child_runs.is_task_generated_session_title(
        "新しいコーディングセッション"
    )
    assert not child_runs.is_task_generated_session_title("")
    assert not child_runs.is_task_generated_session_title(None)


# --- coding session reuse ---


def _mock_coding_run(monkeypatch, worker_text="code done"):
    monkeypatch.setattr(
        projects_service,
        "get_project_detail",
        lambda project_id: {"project_id": project_id, "project_path": "/repo/demo"},
    )
    monkeypatch.setattr(coding_backend, "validate_git_repo", lambda path: "/repo/demo")
    monkeypatch.setattr(
        coding_store,
        "get_run",
        lambda run_id: {"run_id": run_id, "status": "completed"},
    )
    monkeypatch.setattr(
        coding_store,
        "list_messages",
        lambda session_id: [
            {"role": "worker", "content": worker_text},
            {"role": "orchestrator", "content": "orchestrated done"},
        ],
    )


def test_coding_adapter_reuses_session_within_task(monkeypatch):
    _mock_coding_run(monkeypatch)
    created_titles = []
    sessions = {
        "cses_first": {
            "session_id": "cses_first",
            "project_id": 7,
            "backend": "opencode",
        }
    }

    def fake_create_session(project_id, backend, repo_path, title=None):
        created_titles.append(title)
        session_id = f"cses_new_{len(created_titles)}"
        sessions[session_id] = {
            "session_id": session_id,
            "project_id": project_id,
            "backend": backend,
        }
        return sessions[session_id]

    started_in = []
    run_counter = {"n": 0}

    def fake_start(session_id, content, created_instance_id=None):
        started_in.append(session_id)
        run_counter["n"] += 1
        return {"message_id": "m"}, {"run_id": f"crun_{run_counter['n']}"}

    monkeypatch.setattr(coding_store, "create_session", fake_create_session)
    monkeypatch.setattr(coding_store, "start_queued_run", fake_start)
    monkeypatch.setattr(coding_store, "get_session", lambda sid: sessions.get(sid))
    monkeypatch.setattr(coding_store, "get_active_run_for_session", lambda sid: None)

    task = store.create_task("coding reuse job")
    plan = _legacy_task_plan(
        task["task_id"],
        "coding_cli",
        {"project_id": 7},
        {"task": "実装調査をしてコミット"},
    )
    step = plan["plan"]["steps"][0]
    adapter = CodingAdapter()

    first = adapter.execute_step(task, plan, 0, step)
    assert first.child_run_id == "crun_1"
    assert started_in == ["cses_new_1"]
    # Content-aware title, not the fixed pattern.
    assert created_titles[0] != f"Task {task['task_id']} step 0"
    assert "実装調査" in created_titles[0]

    followup = dict(step, inputs={"task": "結果を検証してコミットSHAを報告"})
    second = adapter.execute_step(task, plan, 1, followup)
    assert second.child_run_id == "crun_2"
    # Same session reused: no second create_session call.
    assert started_in == ["cses_new_1", "cses_new_1"]
    assert len(created_titles) == 1

    started_events = [
        e
        for e in store.list_task_events(task["task_id"])
        if e["event_type"] == "child_run_started"
    ]
    assert [e["payload"]["session_id"] for e in started_events] == [
        "cses_new_1",
        "cses_new_1",
    ]
    assert [e["payload"]["session_reused"] for e in started_events] == [False, True]


def test_coding_adapter_new_session_for_fresh_or_other_project(monkeypatch):
    _mock_coding_run(monkeypatch)
    created = []

    def fake_create_session(project_id, backend, repo_path, title=None):
        session_id = f"cses_{project_id}_{len(created)}"
        created.append(session_id)
        return {"session_id": session_id, "project_id": project_id, "backend": backend}

    started_in = []

    def fake_start(session_id, content, created_instance_id=None):
        started_in.append(session_id)
        return {"message_id": "m"}, {"run_id": f"crun_{session_id}"}

    monkeypatch.setattr(coding_store, "create_session", fake_create_session)
    monkeypatch.setattr(coding_store, "start_queued_run", fake_start)
    monkeypatch.setattr(
        coding_store,
        "get_session",
        lambda sid: {"session_id": sid, "project_id": 7, "backend": "opencode"},
    )
    monkeypatch.setattr(coding_store, "get_active_run_for_session", lambda sid: None)

    task = store.create_task("coding fresh job")
    plan = _legacy_task_plan(
        task["task_id"], "coding_cli", {"project_id": 7}, {"task": "最初の作業"}
    )
    adapter = CodingAdapter()
    adapter.execute_step(task, plan, 0, plan["plan"]["steps"][0])

    # Explicit fresh_session request bypasses reuse.
    fresh_step = dict(
        plan["plan"]["steps"][0], inputs={"task": "別文脈の作業", "fresh_session": True}
    )
    adapter.execute_step(task, plan, 1, fresh_step)
    assert started_in[0] != started_in[1]
    assert len(created) == 2

    # A different project never reuses the first session.
    other_step = dict(
        plan["plan"]["steps"][0],
        target={"project_id": 9},
        inputs={"task": "別プロジェクトの作業"},
    )
    adapter.execute_step(task, plan, 2, other_step)
    assert len(created) == 3


def test_coding_adapter_recovers_when_prior_session_missing(monkeypatch):
    _mock_coding_run(monkeypatch)
    monkeypatch.setattr(
        coding_store,
        "create_session",
        lambda project_id, backend, repo_path, title=None: {
            "session_id": "cses_recovery",
            "project_id": project_id,
            "backend": backend,
        },
    )
    monkeypatch.setattr(
        coding_store,
        "start_queued_run",
        lambda session_id, content, created_instance_id=None: (
            {"message_id": "m"},
            {"run_id": "crun_new"},
        ),
    )
    # Prior event references a session that no longer exists.
    monkeypatch.setattr(coding_store, "get_session", lambda sid: None)
    monkeypatch.setattr(coding_store, "get_active_run_for_session", lambda sid: None)

    task = store.create_task("coding recovery job")
    plan = _legacy_task_plan(
        task["task_id"], "coding_cli", {"project_id": 7}, {"task": "最初の作業"}
    )
    adapter = CodingAdapter()
    adapter.execute_step(task, plan, 0, plan["plan"]["steps"][0])
    second = adapter.execute_step(
        task, plan, 1, dict(plan["plan"]["steps"][0], inputs={"task": "続けて作業"})
    )
    assert second.child_run_id == "crun_new"


# --- agent session reuse ---


def _mock_agent_run(monkeypatch, final_text="agent done"):
    monkeypatch.setattr(
        agent_store, "get_agent", lambda agent_id: {"agent_id": agent_id}
    )
    monkeypatch.setattr(
        agent_store,
        "get_run",
        lambda run_id: {
            "run_id": run_id,
            "status": "succeeded",
            "assistant_message_id": "amsg_x",
            "error_message": None,
        },
    )
    monkeypatch.setattr(
        agent_store,
        "get_message",
        lambda message_id: {"message_id": message_id, "content": final_text},
    )
    monkeypatch.setattr(agent_store, "list_runs", lambda session_id: [])


def test_agent_adapter_reuses_session_within_task(monkeypatch):
    _mock_agent_run(monkeypatch)
    created_titles = []

    def fake_create_session(agent_id, title=None):
        created_titles.append(title)
        return {"session_id": f"asess_{len(created_titles)}", "agent_id": agent_id}

    started_in = []
    run_counter = {"n": 0}

    def fake_start(session_id, content, created_instance_id=None):
        started_in.append(session_id)
        run_counter["n"] += 1
        return {"message_id": "m"}, {"run_id": f"arun_{run_counter['n']}"}

    monkeypatch.setattr(agent_store, "create_session", fake_create_session)
    monkeypatch.setattr(agent_store, "start_queued_run", fake_start)
    monkeypatch.setattr(
        agent_store,
        "get_session",
        lambda sid: {"session_id": sid, "agent_id": "agent_1"},
    )

    task = store.create_task("agent reuse job")
    plan = _legacy_task_plan(
        task["task_id"],
        "specialist_agent",
        {"agent_id": "agent_1"},
        {"task": "調査して報告"},
    )
    adapter = AgentAdapter()
    adapter.execute_step(task, plan, 0, plan["plan"]["steps"][0])
    adapter.execute_step(
        task, plan, 1, dict(plan["plan"]["steps"][0], inputs={"task": "追加で確認"})
    )
    assert started_in == ["asess_1", "asess_1"]
    assert len(created_titles) == 1
    assert created_titles[0] != f"Task {task['task_id']} step 0"


# --- capability schema: fresh_session ---


def test_delegate_inputs_default_to_session_reuse():
    coding_inputs = schemas.validate_capability_inputs("coding_cli", {"task": "work"})
    assert coding_inputs == {"task": "work", "fresh_session": False}
    agent_inputs = schemas.validate_capability_inputs(
        "specialist_agent", {"task": "work", "fresh_session": True}
    )
    assert agent_inputs == {"task": "work", "fresh_session": True}


# --- orchestrator observation fidelity ---


def test_observation_truncation_preserves_completion_evidence():
    head = "実装内容の説明。" * 300
    tail = "テスト: 9 passed。コミットSHA: b918a5495454923cb483b74abc6d5135eb5a9641"
    text = head + "\n" + tail
    assert len(text) > orchestrator_module.OBSERVATION_HEAD + (
        orchestrator_module.OBSERVATION_TAIL
    )
    shortened = orchestrator_module._truncate_observation(text)
    assert len(shortened) <= 2001 + len("\n...() chars omitted...\n") + 20
    assert "b918a5495454923cb483b74abc6d5135eb5a9641" in shortened
    assert "9 passed" in shortened
    assert "omitted" in shortened


def test_orchestrator_prompt_keeps_tail_evidence():
    observation = (
        "中間経過の説明。" * 100
    ) + "\nコミットSHA: deadbeef12345678。テスト29件成功。"
    prompt = orchestrator_module.build_orchestrator_prompt(
        {"prompt_text": "job"},
        orchestrator_module.DirectionalPlan(
            purpose="p",
            capabilities=[{"capability_key": "coding_cli", "intent": "i"}],
            completion_criteria="d",
        ),
        {"capability_keys": ["coding_cli"]},
        {"coding_cli": "task string optional"},
        [
            {
                "action_index": 0,
                "capability_key": "coding_cli",
                "inputs": {"task": "implement"},
                "observation": observation,
            }
        ],
    )
    assert "deadbeef12345678" in prompt
    assert "29件成功" in prompt
