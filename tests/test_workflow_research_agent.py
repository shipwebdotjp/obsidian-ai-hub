"""Workflow `research_agent` execution: Task-compatible Step and end-to-end runs.

The Capability bridge in ``workflow/runners.py`` must always send
``target: {}`` because the Task Step contract requires ``target`` to be an
object even when the capability ignores it. The last two tests are the
operation-scenario contract for the irreversible Vault write (see
docs/development-quality-playbook.md):
- published + approved research Workflow -> worker -> Research Job success,
  report published to the Vault exactly once, Run completed
- failure: research generation fails -> Run failed, nothing in the Vault
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.research import db as research_db
from obsidian_ai_hub.research import runner as research_runner
from obsidian_ai_hub.tasks import execution as task_execution
from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow import worker as workflow_worker
from obsidian_ai_hub.workflow.runners import DefaultNodeRunner


@pytest.fixture
def client(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


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


class _CaptureExecutor:
    """Fake Task executor recording the Steps it receives."""

    def __init__(self):
        self.steps = []

    def execute_step(self, task, plan, step_index, step):
        self.steps.append(dict(step))
        return task_execution.StepResult(
            step_index=step_index,
            capability_key=str(step.get("capability_key")),
            summary='{"ok": true}',
        )


def test_capability_bridge_sends_empty_target():
    executor = _CaptureExecutor()
    runner = DefaultNodeRunner()
    runner._executor = executor
    node = {
        "node_id": str(uuid.uuid4()),
        "node_type": "capability",
        "config": {"capability_key": "research_agent"},
    }
    outcome = runner.run(
        node=node,
        inputs={"theme": "テストテーマ", "mode": "internal"},
        context={"run_id": "wrun_test"},
    )
    assert outcome.status == "succeeded"
    assert len(executor.steps) == 1
    step = executor.steps[0]
    assert step["capability_key"] == "research_agent"
    assert step["target"] == {}
    assert step["inputs"]["theme"] == "テストテーマ"
    assert isinstance(step["inputs"]["theme"], str)
    # The bridge owns a short-lived Task that ends terminal (never queued
    # where the Task worker could claim it).
    bridge_tasks = [
        t
        for t in task_store.list_tasks()
        if "wrun_test" in str(t.get("prompt_text") or "")
    ]
    assert len(bridge_tasks) == 1
    assert bridge_tasks[0]["status"] == "completed"


class _BoomExecutor:
    def execute_step(self, task, plan, step_index, step):
        raise ValueError("boom")


def test_capability_bridge_marks_task_failed_on_error():
    runner = DefaultNodeRunner()
    runner._executor = _BoomExecutor()
    node = {
        "node_id": str(uuid.uuid4()),
        "node_type": "capability",
        "config": {"capability_key": "research_agent"},
    }
    with pytest.raises(ValueError, match="boom"):
        runner.run(
            node=node,
            inputs={"theme": "x"},
            context={"run_id": "wrun_boom"},
        )
    bridge_tasks = [
        t
        for t in task_store.list_tasks()
        if "wrun_boom" in str(t.get("prompt_text") or "")
    ]
    assert len(bridge_tasks) == 1
    assert bridge_tasks[0]["status"] == "failed"


def _research_graph(theme):
    research_id = str(uuid.uuid4())
    end_id = str(uuid.uuid4())
    nodes = [
        {
            "node_id": research_id,
            "node_type": "capability",
            "config": {
                "capability_key": "research_agent",
                "inputs": {"theme": theme, "mode": "internal"},
            },
        },
        {
            "node_id": end_id,
            "node_type": "terminal",
            "config": {"outcome": "success"},
        },
    ]
    edges = [
        {
            "edge_id": str(uuid.uuid4()),
            "source_node_id": research_id,
            "target_node_id": end_id,
            "order_index": 0,
        }
    ]
    return nodes, edges


def _publish_approved_run(client, name, theme):
    task_store.sync_capabilities()
    created = client.post("/api/v1/workflows", json={"name": name}).json()
    revision_id = created["revision"]["revision_id"]
    nodes, edges = _research_graph(theme)
    updated = client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={"inputs_schema": {"type": "object"}, "nodes": nodes, "edges": edges},
    )
    assert updated.status_code == 200
    published = client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")
    assert published.status_code == 200
    run = client.post(
        f"/api/v1/workflows/revisions/{revision_id}/runs", json={"inputs": {}}
    ).json()
    assert run["status"] == "waiting_approval"
    approved = client.post(f"/api/v1/workflows/runs/{run['run_id']}/approve").json()
    assert approved["status"] == "queued"
    return run["run_id"]


def test_workflow_research_agent_end_to_end(
    _fake_llm, _sync_research_execution, test_memory_db_path, client
):
    theme = "ワークフローリサーチテーマ"
    run_id = _publish_approved_run(client, "wf-research-e2e", theme)

    assert workflow_worker.process_one("e2e-instance") is True

    finished = workflow_store.get_run(run_id)
    assert finished["status"] == "completed"
    record = research_db.find_exact_duplicate(research_db.normalize_theme_key(theme))
    job = research_db.latest_job(record["theme_id"])
    assert job["status"] == "succeeded"
    assert job["is_published"] == 1
    assert os.path.exists(job["output_path"])
    assert len(list(app_config.RESEARCH_OUTPUT_DIR.glob("*.md"))) == 1


def test_workflow_research_agent_failure_publishes_nothing(
    _fake_llm, _sync_research_execution, test_memory_db_path, client, monkeypatch
):
    def boom(*args, **kwargs):
        raise RuntimeError("make report fail")

    monkeypatch.setattr(research_runner, "conduct_research", boom)
    theme = "ワークフロー失敗テーマ"
    run_id = _publish_approved_run(client, "wf-research-fail", theme)

    assert workflow_worker.process_one("e2e-fail-instance") is True

    finished = workflow_store.get_run(run_id)
    assert finished["status"] == "failed"
    record = research_db.find_exact_duplicate(research_db.normalize_theme_key(theme))
    job = research_db.latest_job(record["theme_id"])
    assert job["status"] == "failed"
    assert job["is_published"] == 0
    assert list(app_config.RESEARCH_OUTPUT_DIR.glob("*.md")) == []
