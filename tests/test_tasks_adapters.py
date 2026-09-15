import pytest

import obsidian_ai_hub.agents.registry as registry_module
import obsidian_ai_hub.agents.store as agent_store
import obsidian_ai_hub.coding.store as coding_store
import obsidian_ai_hub.web.services.projects as projects_service
from obsidian_ai_hub.coding import backend as coding_backend
from obsidian_ai_hub.tasks import execution, store
from obsidian_ai_hub.tasks import worker as task_worker
from obsidian_ai_hub.tasks.adapters import CompositeExecutor, get_default_executor
from obsidian_ai_hub.tasks.adapters.agent import AgentAdapter
from obsidian_ai_hub.tasks.adapters.coding import CodingAdapter
from obsidian_ai_hub.tasks.adapters.deviation import (
    build_revised_plan,
    parse_deviation_report,
)
from obsidian_ai_hub.tasks.adapters.registry_tools import RegistryToolExecutor


class FakeTool:
    def __init__(self, result="{}"):
        self.result = result
        self.calls = []

    def invoke(self, inputs):
        self.calls.append(inputs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _task_with_plan(capability_key, target, inputs=None):
    task = store.create_task("adapter job")
    plan = store.create_plan(
        task["task_id"],
        {
            "purpose": "p",
            "steps": [
                {
                    "capability_key": capability_key,
                    "title": "step",
                    "target": target,
                    "inputs": inputs or {},
                    "side_effects": "none",
                }
            ],
            "completion_criteria": "done",
        },
        {capability_key: "auto"},
    )
    return task, plan


def test_registry_tool_success_and_inputs(monkeypatch):
    fake = FakeTool('{"events": []}')
    monkeypatch.setattr(
        registry_module,
        "TOOL_DEFINITIONS",
        {
            "calendar_read": {
                "get_tool": lambda: fake,
                "input_model": registry_module.CalendarReadInput,
            }
        },
    )
    task, plan = _task_with_plan(
        "calendar_read", {}, {"start_date": "2026-09-14", "end_date": "2026-09-15"}
    )
    result = RegistryToolExecutor().execute_step(
        task, plan, 0, plan["plan"]["steps"][0]
    )
    assert result.summary == '{"events": []}'
    assert fake.calls == [{"start_date": "2026-09-14", "end_date": "2026-09-15"}]


def test_registry_tool_allows_run_shell(monkeypatch):
    fake = FakeTool('{"exit_code": 0}')
    monkeypatch.setattr(
        registry_module,
        "TOOL_DEFINITIONS",
        {
            "run_shell": {
                "get_tool": lambda: fake,
                "input_model": registry_module.RunShellInput,
            }
        },
    )
    task, plan = _task_with_plan("run_shell", {}, {"command": "echo hi"})
    result = RegistryToolExecutor().execute_step(
        task, plan, 0, plan["plan"]["steps"][0]
    )
    assert result.summary == '{"exit_code": 0}'
    assert fake.calls == [{"command": "echo hi"}]


def test_registry_tool_rejects_excluded_tools():
    for excluded in (
        "ask_user",
        "agent_delegate",
    ):
        task, plan = _task_with_plan(excluded, {}, {})
        with pytest.raises(ValueError, match="not a .* capability|not registered"):
            RegistryToolExecutor().execute_step(task, plan, 0, plan["plan"]["steps"][0])


def test_registry_tool_unknown_registration(monkeypatch):
    monkeypatch.setattr(registry_module, "TOOL_DEFINITIONS", {})
    task, plan = _task_with_plan("web_search", {}, {"query": "x"})
    # With an empty registry the catalog itself has no web_search.
    with pytest.raises(ValueError, match="not a Task capability|not registered"):
        RegistryToolExecutor().execute_step(task, plan, 0, plan["plan"]["steps"][0])


def test_registry_tool_invalid_inputs_and_tool_error(monkeypatch):
    from obsidian_ai_hub.handler.web_search import WebSearchInput

    fake = FakeTool('{"ok": true}')
    monkeypatch.setattr(
        registry_module,
        "TOOL_DEFINITIONS",
        {"web_search": {"get_tool": lambda: fake, "input_model": WebSearchInput}},
    )
    task, plan = _task_with_plan("web_search", {}, {"query": "x"})
    bad_step = dict(plan["plan"]["steps"][0], inputs=["not", "a", "dict"])
    with pytest.raises(ValueError, match="must be an object"):
        RegistryToolExecutor().execute_step(task, plan, 0, bad_step)

    failing = FakeTool(ValueError("boom"))
    monkeypatch.setattr(
        registry_module,
        "TOOL_DEFINITIONS",
        {"web_search": {"get_tool": lambda: failing, "input_model": WebSearchInput}},
    )
    with pytest.raises(ValueError, match="Registry tool 'web_search' failed"):
        RegistryToolExecutor().execute_step(task, plan, 0, plan["plan"]["steps"][0])


def test_memory_propose_uses_task_context(monkeypatch):
    seen = {}

    def factory(ctx):
        seen["ctx"] = ctx
        return FakeTool('{"status": "ok"}')

    monkeypatch.setattr(
        registry_module,
        "TOOL_DEFINITIONS",
        {
            "memory_propose": {
                "get_tool_with_context": factory,
                "input_model": registry_module.MemoryProposeInput,
            }
        },
    )
    task, plan = _task_with_plan("memory_propose", {}, {"content": "x", "kind": "fact"})
    RegistryToolExecutor().execute_step(task, plan, 0, plan["plan"]["steps"][0])
    ctx = seen["ctx"]
    assert ctx["agent_id"] == f"task-agent:{task['task_id']}"
    assert ctx["session_id"] == task["task_id"]
    assert ctx["run_id"] == task["task_id"]
    assert ctx["user_message_id"]


def test_deviation_protocol():
    assert parse_deviation_report("plain text") is None
    report = parse_deviation_report(
        'prefix <deviation_request>{"reason": "need code", "steps": [{"a": 1}]}</deviation_request> suffix'
    )
    assert report == {"reason": "need code", "steps": [{"a": 1}]}
    with pytest.raises(ValueError, match="Invalid deviation_request"):
        parse_deviation_report("<deviation_request>not json</deviation_request>")
    with pytest.raises(ValueError, match="reason"):
        parse_deviation_report('<deviation_request>{"steps": []}</deviation_request>')

    revised = build_revised_plan(
        {"purpose": "p", "steps": [{"title": "old"}], "completion_criteria": "d"},
        {
            "reason": "r",
            "steps": [
                {
                    "capability_key": "web_search",
                    "title": "new",
                    "target": {},
                    "inputs": {},
                }
            ],
        },
    )
    assert [s["title"] for s in revised["steps"]] == ["old", "new"]

    with pytest.raises(ValueError, match="unknown capability"):
        build_revised_plan(
            {"purpose": "p", "steps": []},
            {
                "reason": "r",
                "steps": [
                    {
                        "capability_key": "ask_user",
                        "title": "evil",
                        "target": {},
                        "inputs": {},
                    }
                ],
            },
        )

    allowed = build_revised_plan(
        {"purpose": "p", "steps": [{"title": "old"}], "completion_criteria": "d"},
        {
            "reason": "r",
            "steps": [
                {
                    "capability_key": "run_shell",
                    "title": "shell it",
                    "target": {},
                    "inputs": {"command": "echo hi"},
                }
            ],
        },
    )
    assert [s["title"] for s in allowed["steps"]] == ["old", "shell it"]
    with pytest.raises(ValueError, match="target/inputs must be objects"):
        build_revised_plan(
            {"purpose": "p", "steps": []},
            {
                "reason": "r",
                "steps": [
                    {
                        "capability_key": "web_search",
                        "title": "bad",
                        "target": {},
                        "inputs": "nope",
                    }
                ],
            },
        )


def _mock_agent_success(monkeypatch, final_text="done result"):
    monkeypatch.setattr(
        agent_store, "get_agent", lambda agent_id: {"agent_id": agent_id}
    )
    monkeypatch.setattr(
        agent_store,
        "create_session",
        lambda agent_id, title=None: {"session_id": "asess_x"},
    )
    monkeypatch.setattr(
        agent_store,
        "start_queued_run",
        lambda session_id, content, created_instance_id=None: (
            {"message_id": "m"},
            {"run_id": "arun_x"},
        ),
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


def test_agent_adapter_success(monkeypatch):
    _mock_agent_success(monkeypatch)
    task, plan = _task_with_plan("specialist_agent", {"agent_id": "agent_1"})
    result = AgentAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])
    assert result.summary == "done result"
    assert result.child_kind == "agent"
    assert result.child_run_id == "arun_x"
    events = store.list_task_events(task["task_id"])
    assert [e["event_type"] for e in events] == ["child_run_started"]
    assert events[0]["payload"]["child_run_id"] == "arun_x"


def test_agent_adapter_unknown_agent(monkeypatch):
    monkeypatch.setattr(agent_store, "get_agent", lambda agent_id: None)
    task, plan = _task_with_plan("specialist_agent", {"agent_id": "missing"})
    with pytest.raises(ValueError, match="unregistered agent"):
        AgentAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])


def test_agent_adapter_deviation(monkeypatch):
    _mock_agent_success(
        monkeypatch,
        'result <deviation_request>{"reason": "need code", "steps": [{"capability_key": "coding_cli", "title": "code it", "target": {}, "inputs": {}}]}</deviation_request>',
    )
    task, plan = _task_with_plan("specialist_agent", {"agent_id": "agent_1"})
    with pytest.raises(execution.DeviationReported) as exc_info:
        AgentAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])
    assert exc_info.value.reason == "need code"
    assert len(exc_info.value.revised_plan["steps"]) == 2


def test_agent_adapter_failed_and_cancelled_child(monkeypatch):
    _mock_agent_success(monkeypatch)
    monkeypatch.setattr(
        agent_store,
        "get_run",
        lambda run_id: {
            "run_id": run_id,
            "status": "failed",
            "error_message": "llm down",
        },
    )
    task, plan = _task_with_plan("specialist_agent", {"agent_id": "agent_1"})
    with pytest.raises(ValueError, match="llm down"):
        AgentAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])

    monkeypatch.setattr(
        agent_store,
        "get_run",
        lambda run_id: {"run_id": run_id, "status": "cancelled"},
    )
    with pytest.raises(execution.TaskCancelled):
        AgentAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])


def test_agent_adapter_propagates_task_cancel(monkeypatch):
    _mock_agent_success(monkeypatch)
    cancelled = []
    # The cancel path reads the run once more (HITL-link lookup), so the
    # queue holds an extra state: the cancelling run seen by that lookup.
    states = [
        {"status": "running"},
        {"status": "running"},
        {"status": "cancelling"},
        {"status": "cancelled"},
    ]
    monkeypatch.setattr(agent_store, "get_run", lambda run_id: states.pop(0))
    monkeypatch.setattr(
        agent_store, "request_cancel_run", lambda run_id: cancelled.append(run_id) or {}
    )
    task = store.create_task("cancel job")
    store.claim_task("worker-1", "planning")
    store.transition_task_status(task["task_id"], "running")
    plan_record = store.create_plan(
        task["task_id"],
        {
            "purpose": "p",
            "steps": [
                {
                    "capability_key": "specialist_agent",
                    "title": "step",
                    "target": {"agent_id": "agent_1"},
                    "inputs": {},
                    "side_effects": "none",
                }
            ],
            "completion_criteria": "done",
        },
        {"specialist_agent": "plan_required"},
    )

    calls = {"n": 0}
    original_get_run = agent_store.get_run

    def staged_get_run(run_id):
        calls["n"] += 1
        if calls["n"] == 2:
            store.transition_task_status(task["task_id"], "cancelling")
        return original_get_run(run_id)

    monkeypatch.setattr(agent_store, "get_run", staged_get_run)
    adapter = AgentAdapter(poll_interval=0.001)
    with pytest.raises(execution.TaskCancelled):
        adapter.execute_step(task, plan_record, 0, plan_record["plan"]["steps"][0])
    assert cancelled == ["arun_x"]


def _mock_coding_success(
    monkeypatch, worker_text="code done", orch_text="orchestrated done"
):
    monkeypatch.setattr(
        projects_service,
        "get_project_detail",
        lambda project_id: {"project_id": project_id, "project_path": "/repo/demo"},
    )
    monkeypatch.setattr(coding_backend, "validate_git_repo", lambda path: "/repo/demo")
    monkeypatch.setattr(
        coding_store,
        "create_session",
        lambda project_id, backend, repo_path, title=None: {"session_id": "cses_x"},
    )
    monkeypatch.setattr(
        coding_store,
        "start_queued_run",
        lambda session_id, content, created_instance_id=None: (
            {"message_id": "m"},
            {"run_id": "crun_x"},
        ),
    )
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
            {"role": "orchestrator", "content": orch_text},
        ],
    )


def test_coding_adapter_build_content_task_and_fallback():
    adapter = CodingAdapter()
    task = {"task_id": "t1"}
    plan = {"plan": {"purpose": "Refactor codebase"}}

    # When task string is present and non-empty after strip
    step_with_task = {"inputs": {"task": "  Fix bug in parser  ", "fresh_session": True}}
    content = adapter._build_content(task, plan, 0, step_with_task)
    assert content == "Fix bug in parser"

    # When task string is empty or whitespace, fallback to purpose
    step_blank_task = {"inputs": {"task": "   "}}
    content_fallback = adapter._build_content(task, plan, 0, step_blank_task)
    assert content_fallback == "Refactor codebase"

    # Ensure no step headers, deviation instructions or JSON inputs in content
    assert "TaskのPlan Step" not in content
    assert "<deviation_request>" not in content
    assert "fresh_session" not in content


def test_coding_adapter_ignores_deviation_tags_and_completes_normally(monkeypatch):
    deviation_text = (
        'done result <deviation_request>{"reason": "need code", "steps": []}</deviation_request>'
    )
    _mock_coding_success(monkeypatch, orch_text=deviation_text)
    task, plan = _task_with_plan("coding_cli", {"project_id": 7})
    result = CodingAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])
    assert result.summary == deviation_text
    assert result.child_kind == "coding"
    assert result.child_run_id == "crun_x"


def test_coding_adapter_success(monkeypatch):
    _mock_coding_success(monkeypatch)
    task, plan = _task_with_plan("coding_cli", {"project_id": 7})
    result = CodingAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])
    assert result.summary == "orchestrated done"
    assert result.child_kind == "coding"
    assert result.child_run_id == "crun_x"


def test_coding_adapter_uses_orchestrator_final_text(monkeypatch):
    _mock_coding_success(
        monkeypatch,
        worker_text="raw cli output",
        orch_text="final report with SHA abc123",
    )
    task, plan = _task_with_plan("coding_cli", {"project_id": 7})
    result = CodingAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])
    assert result.summary == "final report with SHA abc123"


def test_coding_adapter_requires_orchestrator_text(monkeypatch):
    _mock_coding_success(monkeypatch)
    monkeypatch.setattr(
        coding_store,
        "list_messages",
        lambda session_id: [{"role": "worker", "content": "only worker"}],
    )
    task, plan = _task_with_plan("coding_cli", {"project_id": 7})
    with pytest.raises(ValueError, match="produced no messages"):
        CodingAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])


def test_coding_adapter_validates_target(monkeypatch):
    _mock_coding_success(monkeypatch)
    task, plan = _task_with_plan("coding_cli", {"project_id": 7, "backend": "bogus"})
    with pytest.raises(ValueError, match="target invalid"):
        CodingAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])

    task2, plan2 = _task_with_plan("coding_cli", {"project_id": "not-an-int"})
    with pytest.raises(ValueError, match="target invalid"):
        CodingAdapter().execute_step(task2, plan2, 0, plan2["plan"]["steps"][0])

    monkeypatch.setattr(projects_service, "get_project_detail", lambda project_id: None)
    task3, plan3 = _task_with_plan("coding_cli", {"project_id": 9})
    with pytest.raises(ValueError, match="unregistered project"):
        CodingAdapter().execute_step(task3, plan3, 0, plan3["plan"]["steps"][0])


def test_coding_adapter_failed_child(monkeypatch):
    _mock_coding_success(monkeypatch)
    monkeypatch.setattr(
        coding_store,
        "get_run",
        lambda run_id: {
            "run_id": run_id,
            "status": "failed",
            "error_message": "cli died",
        },
    )
    task, plan = _task_with_plan("coding_cli", {"project_id": 7})
    with pytest.raises(ValueError, match="cli died"):
        CodingAdapter().execute_step(task, plan, 0, plan["plan"]["steps"][0])


def test_composite_executor_dispatch_and_rejection(monkeypatch):
    from obsidian_ai_hub.handler.web_search import WebSearchInput

    fake = FakeTool('{"ok": true}')
    monkeypatch.setattr(
        registry_module,
        "TOOL_DEFINITIONS",
        {"web_search": {"get_tool": lambda: fake, "input_model": WebSearchInput}},
    )
    task, plan = _task_with_plan("web_search", {}, {"query": "x"})
    result = get_default_executor().execute_step(
        task, plan, 0, plan["plan"]["steps"][0]
    )
    assert result.summary == '{"ok": true}'

    task2, plan2 = _task_with_plan("ask_user", {}, {})
    with pytest.raises(ValueError, match="not a .* capability"):
        CompositeExecutor().execute_step(task2, plan2, 0, plan2["plan"]["steps"][0])


def test_worker_stops_on_disabled_capability():
    store.update_capability("web_search", enabled=False)
    task = store.create_task("disabled job")
    store.claim_task("worker-1", "planning")
    store.transition_task_status(task["task_id"], "running")
    _, plan = _task_with_plan("web_search", {}, {"query": "x"})
    plan_record = store.create_plan(
        task["task_id"], plan["plan"], {"web_search": "auto"}
    )
    task_worker._run_execution(task["task_id"], plan_record, None)
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "waiting_reapproval"
    plans = store.list_plans(task["task_id"])
    assert plans[-1]["status"] == "pending"


def test_worker_task_cancelled_path():
    class CancellingExecutor:
        def execute_step(self, task, plan, step_index, step):
            raise execution.TaskCancelled("cancelled")

    task = store.create_task("cancel path job")
    store.claim_task("worker-1", "planning")
    store.transition_task_status(task["task_id"], "running")
    _, plan = _task_with_plan("web_search", {}, {"query": "x"})
    plan_record = store.create_plan(
        task["task_id"], plan["plan"], {"web_search": "auto"}
    )
    store.set_active_child(task["task_id"], "agent", "arun_stale")
    task_worker._run_execution(task["task_id"], plan_record, CancellingExecutor())
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "cancelled"
    assert updated["active_child_kind"] is None
    assert updated["active_child_run_id"] is None


def test_child_wait_timeout_fails_step(monkeypatch):
    _mock_agent_success(monkeypatch)
    monkeypatch.setattr(
        agent_store,
        "get_run",
        lambda run_id: {"run_id": run_id, "status": "running"},
    )
    task, plan = _task_with_plan("specialist_agent", {"agent_id": "agent_1"})
    adapter = AgentAdapter(poll_interval=0.001, timeout_secs=0.01)
    with pytest.raises(TimeoutError, match="did not finish"):
        adapter.execute_step(task, plan, 0, plan["plan"]["steps"][0])


def test_interrupted_task_is_not_reclaimed():
    task = store.create_task("stays interrupted")
    store.claim_task("worker-1", "planning")
    store.transition_task_status(task["task_id"], "interrupted")
    assert task_worker._process_one("worker-1", None) is False
    assert store.get_task(task["task_id"])["status"] == "interrupted"
