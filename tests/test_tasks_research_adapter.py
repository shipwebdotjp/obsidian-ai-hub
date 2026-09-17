"""Tests for the Task `research_agent` capability and its ResearchAdapter.

Unit tests mock the research runner boundaries. The last two tests are the
operation-scenario contract for the irreversible Vault write (see
docs/development-quality-playbook.md):
- theme/job records -> background job -> report generated -> Vault file once
- failure: the step fails and nothing is published to the Vault
"""

import pytest

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.research import runner as research_runner
from obsidian_ai_hub.research import db as research_db
from obsidian_ai_hub.tasks.adapters import CompositeExecutor
from obsidian_ai_hub.tasks.adapters.research import ResearchAdapter
from obsidian_ai_hub.tasks import execution


def _task_with_research_step(inputs):
    task = task_store.create_task("research job")
    plan = task_store.create_plan(
        task["task_id"],
        {
            "purpose": "p",
            "steps": [
                {
                    "capability_key": "research_agent",
                    "title": "step",
                    "target": {},
                    "inputs": inputs,
                    "side_effects": "writes research report to vault",
                }
            ],
            "completion_criteria": "done",
        },
        {"research_agent": "auto"},
    )
    return task, plan


def _fakes(monkeypatch, job_status="succeeded", error=None, markdown="# report"):
    submitted = []

    def create(theme, mode="auto", context=None, output_style=None):
        theme_rec = research_db.create_theme(
            theme=theme, kind="explore", confidence=1.0, status="candidate"
        )
        job = research_db.create_job(theme_rec["theme_id"])
        return theme_rec, job

    def submit(theme_id, job_id, mode="auto", output_style=None, context=None):
        submitted.append((theme_id, job_id, mode))
        research_db.update_job(
            job_id,
            status=job_status,
            generated_title="Fake Title",
            mode=mode,
            markdown=markdown,
            error=error,
        )

    monkeypatch.setattr(research_runner, "get_or_create_theme_and_job", create)
    monkeypatch.setattr(research_runner, "submit_research_job_bg", submit)
    return submitted


def test_research_adapter_success(monkeypatch):
    submitted = _fakes(monkeypatch)
    task, plan = _task_with_research_step({"theme": "テーマ", "mode": "web"})
    result = ResearchAdapter(poll_interval=0.05).execute_step(
        task, plan, 0, plan["plan"]["steps"][0]
    )
    assert len(submitted) == 1
    theme_id, job_id, mode = submitted[0]
    assert mode == "web"
    assert result.child_kind == "research"
    assert result.child_run_id == job_id
    assert "Fake Title" in result.summary
    assert "# report" in result.summary
    events = task_store.list_task_events(task["task_id"])
    assert [e["event_type"] for e in events] == ["child_run_started"]
    assert events[0]["payload"]["child_kind"] == "research"
    assert events[0]["payload"]["child_run_id"] == job_id
    assert events[0]["payload"]["theme_id"] == theme_id


def test_research_adapter_failed_job(monkeypatch):
    _fakes(monkeypatch, job_status="failed", error="llm down")
    task, plan = _task_with_research_step({"theme": "テーマ"})
    with pytest.raises(ValueError, match="llm down"):
        ResearchAdapter(poll_interval=0.05).execute_step(
            task, plan, 0, plan["plan"]["steps"][0]
        )


def test_research_adapter_invalid_inputs(monkeypatch):
    submitted = _fakes(monkeypatch)
    task, plan = _task_with_research_step({"mode": "web"})
    with pytest.raises(ValueError, match="inputs invalid"):
        ResearchAdapter(poll_interval=0.05).execute_step(
            task, plan, 0, plan["plan"]["steps"][0]
        )
    assert submitted == []


def test_research_adapter_rejects_non_research_capability(monkeypatch):
    _fakes(monkeypatch)
    task, plan = _task_with_research_step({"theme": "x"})
    bad_step = dict(plan["plan"]["steps"][0], capability_key="web_search")
    with pytest.raises(ValueError, match="inputs invalid"):
        ResearchAdapter(poll_interval=0.05).execute_step(
            task, plan, 0, bad_step
        )
    # Dispatch-by-kind keeps registry tools away from this adapter entirely.
    executor = CompositeExecutor()
    with pytest.raises(ValueError):
        executor.execute_step(task, plan, 0, bad_step)


def test_research_adapter_propagates_task_cancel(monkeypatch):
    _fakes(monkeypatch)
    task = task_store.create_task("cancel job")
    task_store.claim_task("worker-1", "planning")
    task_store.transition_task_status(task["task_id"], "running")
    plan_record = task_store.create_plan(
        task["task_id"],
        {
            "purpose": "p",
            "steps": [
                {
                    "capability_key": "research_agent",
                    "title": "step",
                    "target": {},
                    "inputs": {"theme": "テーマ"},
                    "side_effects": "none",
                }
            ],
            "completion_criteria": "done",
        },
        {"research_agent": "auto"},
    )
    states = [{"status": "running"}, {"status": "running"}, {"status": "succeeded"}]

    def fake_get_job(job_id):
        if len(states) == 2:
            task_store.transition_task_status(task["task_id"], "cancelling")
        return states.pop(0) | {"error": None}

    monkeypatch.setattr(research_db, "get_job", fake_get_job)
    with pytest.raises(execution.TaskCancelled):
        ResearchAdapter(poll_interval=0.05).execute_step(
            task, plan_record, 0, plan_record["plan"]["steps"][0]
        )


@pytest.fixture
def _sync_research_execution(monkeypatch):
    """Run the research job synchronously in the scenario tests.

    The background-thread path is exercised by scrubbed unit tests; running
    the job inline here keeps the end-to-end contract deterministic (rapid
    alternating SQLite WAL connections would otherwise race on open/close).
    """

    def sync_submit(theme_id, job_id, mode="auto", output_style=None, context=None):
        research_runner.execute_research_job_sync(
            theme_id, job_id, mode=mode, output_style=output_style, context=context
        )

    monkeypatch.setattr(research_runner, "submit_research_job_bg", sync_submit)


@pytest.fixture
def _fake_llm(monkeypatch):
    monkeypatch.setattr(
        research_runner, "collect_research_context", lambda theme, ctx=None: ctx or ""
    )
    monkeypatch.setattr(
        research_runner,
        "generate_research_title",
        lambda theme, prompt: "シナリオタイトル",
    )
    monkeypatch.setattr(
        research_runner, "conduct_research", lambda *a, **kw: "シナリオ本文"
    )


def _run_signed_plan_step(monkeypatch, steps):
    task = task_store.create_task("scenario task")
    task_store.claim_task("worker-1", "planning")
    task_store.transition_task_status(task["task_id"], "running")
    plan_record = task_store.create_plan(
        task["task_id"],
        {"purpose": "p", "steps": steps, "completion_criteria": "done"},
        {"research_agent": "auto"},
    )
    return task, plan_record


def test_scenario_contract_research_writes_vault_once(
    _fake_llm, _sync_research_execution, monkeypatch
):
    steps = [
        {
            "capability_key": "research_agent",
            "title": "research",
            "target": {},
            "inputs": {"theme": "シナリオテーマ", "mode": "internal"},
            "side_effects": "publish report markdown into the vault",
        }
    ]
    task, plan_record = _run_signed_plan_step(monkeypatch, steps)
    result = ResearchAdapter(poll_interval=0.05).execute_step(
        task, plan_record, 0, plan_record["plan"]["steps"][0]
    )
    theme = research_db.find_exact_duplicate(
        research_db.normalize_theme_key("シナリオテーマ")
    )
    job = research_db.latest_job(theme["theme_id"])
    assert job["status"] == "succeeded"
    assert job["is_published"] == 1
    import os

    assert os.path.exists(job["output_path"])
    assert result.child_kind == "research"
    assert "シナリオタイトル" in result.summary
    # The theme is approved as an effect of the successful publication.
    assert research_db.get_theme(theme["theme_id"])["status"] == "approved"


def test_scenario_contract_failure_never_publishes(_sync_research_execution, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("make report fail")

    monkeypatch.setattr(
        research_runner, "collect_research_context", lambda theme, ctx=None: ctx or ""
    )
    monkeypatch.setattr(
        research_runner,
        "generate_research_title",
        lambda theme, prompt: "失敗タイトル",
    )
    monkeypatch.setattr(research_runner, "conduct_research", boom)
    steps = [
        {
            "capability_key": "research_agent",
            "title": "research",
            "target": {},
            "inputs": {"theme": "失敗テーマ", "mode": "internal"},
            "side_effects": "publish report markdown into the vault",
        }
    ]
    task, plan_record = _run_signed_plan_step(monkeypatch, steps)
    with pytest.raises(ValueError, match="make report fail"):
        ResearchAdapter(poll_interval=0.05).execute_step(
            task, plan_record, 0, plan_record["plan"]["steps"][0]
        )
    from obsidian_ai_hub.utils import config

    theme = research_db.find_exact_duplicate(
        research_db.normalize_theme_key("失敗テーマ")
    )
    job = research_db.latest_job(theme["theme_id"])
    assert job["status"] == "failed"
    assert job["is_published"] == 0
    assert list(config.RESEARCH_OUTPUT_DIR.glob("*.md")) == []
    assert research_db.get_theme(theme["theme_id"])["status"] == "candidate"
