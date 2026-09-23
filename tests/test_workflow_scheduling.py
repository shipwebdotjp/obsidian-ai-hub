"""Scheduler Job -> published Workflow dispatch contract tests.

Covers the irreversible-operation contract for scheduled Workflow execution
(Run creation that can later perform Capability side effects):

| Stage | Source of truth / ID | Persisted | On stop | Side effect |
| --- | --- | --- | --- | --- |
| recurring dispatch | source_kind + job_id + scheduled_for | dispatch + Run (one tx) | same slot never makes a 2nd Run | none yet |
| approval | Run snapshot nodes | `waiting_approval` Run | no Capability runs before approval | none |
| latest published | current published Revision | Run graph/input snapshot | failure records reason, consumes slot | none |
| one-shot dispatch | one_shot row | `dispatched` + Workflow Run | crash leaves no duplicate Run | none yet |

All tests use the isolated per-test SQLite DB; no external service or real
Capability is executed.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from obsidian_ai_hub import job_runner
from obsidian_ai_hub.scheduler_jobs import one_shot, recurring
from obsidian_ai_hub.utils import config
from obsidian_ai_hub.workflow import scheduling, store as workflow_store


@pytest.fixture
def isolated_jobs(monkeypatch, tmp_path):
    job_file = tmp_path / "jobs.test.yml"
    state_file = tmp_path / "last_run.json"
    monkeypatch.setattr(recurring, "TEST_JOB_FILE", job_file)
    monkeypatch.setattr(recurring, "LOCAL_JOB_FILE", job_file)
    monkeypatch.setattr(recurring, "DEFAULT_JOB_FILE", job_file)
    monkeypatch.setattr(recurring, "STATE_FILE", state_file)
    monkeypatch.setattr(recurring, "LOCK_FILE", tmp_path / ".job-config.lock")
    monkeypatch.setattr(recurring, "RUNNER_LOCK_FILE", tmp_path / ".job-runner.lock")
    monkeypatch.setattr(config, "JOB_RUN_STATE_PATH", state_file)
    monkeypatch.setattr(config, "IS_TEST_ENV", True)
    return job_file, state_file


def _node(node_id, node_type, config):
    return {
        "node_id": node_id,
        "node_type": node_type,
        "config": config,
        "parent_loop_node_id": None,
        "ui_position": None,
    }


def _terminal():
    return _node("t", "terminal", {"outcome": "success"})


def _agent_node():
    return _node("a", "agent", {"agent_id": "agent-1"})


def _publish(schema=None, nodes=None, name="wf") -> tuple[str, str]:
    wf = workflow_store.create_workflow(
        name, inputs_schema=schema or {"type": "object"}
    )
    revision = wf["revision"]
    workflow_store.set_revision_graph(
        revision["revision_id"], nodes or [_terminal()], []
    )
    workflow_store.publish_revision(revision["revision_id"])
    return wf["workflow_id"], revision["revision_id"]


def _runs(workflow_id):
    runs, _ = workflow_store.list_runs(workflow_id=workflow_id, limit=100)
    return runs


# --- recurring dispatch ------------------------------------------------------


def test_dispatch_is_idempotent_per_slot(test_memory_db_path):
    workflow_id, _ = _publish()
    first, run1 = scheduling.dispatch_recurring_slot(
        "job1", "2026-01-01T00:00:00", workflow_id, {}
    )
    assert first["status"] == scheduling.DISPATCHED
    assert run1 is not None

    second, run2 = scheduling.dispatch_recurring_slot(
        "job1", "2026-01-01T00:00:00", workflow_id, {}
    )
    assert run2 is None
    assert second["run_id"] == first["run_id"]
    assert len(_runs(workflow_id)) == 1


def test_dispatch_creates_waiting_approval_without_side_effect(test_memory_db_path):
    workflow_id, _ = _publish(nodes=[_agent_node(), _terminal()])
    dispatch, run = scheduling.dispatch_recurring_slot(
        "job1", "2026-01-01T00:00:00", workflow_id, {}
    )
    assert dispatch["status"] == scheduling.DISPATCHED
    assert run is not None
    assert run["status"] == "waiting_approval"
    # The worker can only claim queued runs, so nothing executes before approval.
    assert workflow_store.claim_run("test-instance") is None


def test_dispatch_skip_approval_creates_queued_run_without_gate(test_memory_db_path):
    workflow_id, _ = _publish(nodes=[_agent_node(), _terminal()])
    workflow_store.update_workflow(workflow_id, skip_approval=True)

    dispatch, run = scheduling.dispatch_recurring_slot(
        "job1", "2026-01-01T00:00:00", workflow_id, {}
    )
    assert dispatch["status"] == scheduling.DISPATCHED
    assert run is not None
    assert run["status"] == "queued"
    # The worker claims it without any human approval.
    claimed = workflow_store.claim_run("test-instance")
    assert claimed is not None
    assert claimed["run_id"] == run["run_id"]
    events = workflow_store.list_events(run["run_id"])
    assert any(e["event_type"] == "run_approval_skipped" for e in events)


def test_skip_approval_does_not_change_existing_waiting_run(test_memory_db_path):
    workflow_id, _ = _publish(nodes=[_agent_node(), _terminal()])
    _, run = scheduling.dispatch_recurring_slot(
        "job1", "2026-01-01T00:00:00", workflow_id, {}
    )
    assert run["status"] == "waiting_approval"

    workflow_store.update_workflow(workflow_id, skip_approval=True)

    # The gate decision is fixed at creation; an existing run is untouched.
    refreshed = workflow_store.get_run(run["run_id"])
    assert refreshed["status"] == "waiting_approval"


def test_schema_mismatch_records_failure_and_consumes_slot(test_memory_db_path):
    schema = {
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
    }
    workflow_id, _ = _publish(schema=schema)
    dispatch, run = scheduling.dispatch_recurring_slot(
        "job1", "2026-01-01T00:00:00", workflow_id, {}
    )
    assert run is None
    assert dispatch["status"] == scheduling.FAILED
    assert dispatch["failure_reason"]
    assert _runs(workflow_id) == []

    again, run2 = scheduling.dispatch_recurring_slot(
        "job1", "2026-01-01T00:00:00", workflow_id, {}
    )
    assert run2 is None
    assert again["dispatch_id"] == dispatch["dispatch_id"]


def test_missing_published_revision_is_recorded_failure(test_memory_db_path):
    wf = workflow_store.create_workflow("draft-only")
    workflow_id = wf["workflow_id"]
    dispatch, run = scheduling.dispatch_recurring_slot(
        "job1", "2026-01-01T00:00:00", workflow_id, {}
    )
    assert run is None
    assert dispatch["status"] == scheduling.FAILED


def test_new_revision_used_next_slot_existing_run_keeps_snapshot(test_memory_db_path):
    schema1 = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
    }
    workflow_id, rev1 = _publish(schema=schema1)

    _, run1 = scheduling.dispatch_recurring_slot(
        "job1", "2026-01-01T00:00:00", workflow_id, {"a": "x"}
    )
    assert run1["revision_id"] == rev1

    # Publish a new revision that additionally requires "b".
    draft = workflow_store.create_revision(workflow_id)
    workflow_store.update_revision_schema(
        draft["revision_id"],
        {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "required": ["a", "b"],
        },
    )
    workflow_store.publish_revision(draft["revision_id"])

    # Next slot with the old inputs fails against the new schema...
    failed, run2 = scheduling.dispatch_recurring_slot(
        "job1", "2026-01-02T00:00:00", workflow_id, {"a": "x"}
    )
    assert run2 is None
    assert failed["status"] == scheduling.FAILED

    # ...and valid inputs use the new revision, while the old Run is unchanged.
    _, run3 = scheduling.dispatch_recurring_slot(
        "job1", "2026-01-03T00:00:00", workflow_id, {"a": "x", "b": "y"}
    )
    assert run3["revision_id"] == draft["revision_id"]
    rewritten = workflow_store.get_run(run1["run_id"])
    assert rewritten["revision_id"] == rev1
    assert rewritten["graph_snapshot"]["inputs_schema"]["required"] == ["a"]


def test_job_runner_dispatches_workflow_and_advances_last_run(
    test_memory_db_path, isolated_jobs, monkeypatch
):
    workflow_id, _ = _publish(nodes=[_agent_node(), _terminal()])
    job_file, _ = isolated_jobs
    job_file.write_text(
        "".join(
            [
                "- id: wf_job\n",
                "  enabled: true\n",
                "  schedule:\n",
                "    type: hourly\n",
                "    minute: 0\n",
                "  workflow:\n",
                f"    workflow_id: {workflow_id}\n",
                "    inputs: {}\n",
            ]
        )
    )

    now = datetime(2026, 5, 1, 10, 30, 0)
    result = job_runner.run_cycle(now)
    assert "wf_job" in result["recurring"]
    runs = _runs(workflow_id)
    assert len(runs) == 1
    assert runs[0]["status"] == "waiting_approval"
    assert recurring.load_state()["wf_job"] == now


# --- one-shot workflow -------------------------------------------------------


def test_one_shot_workflow_dispatch_links_run(test_memory_db_path):
    workflow_id, _ = _publish()
    job = one_shot.register_one_shot_workflow_job(workflow_id, {})
    assert job["target_kind"] == "workflow"
    assert job["status"] == "queued"

    finished = one_shot.run_due_one_shot_jobs()
    assert [j["job_id"] for j in finished] == [job["job_id"]]
    row = one_shot.get_one_shot_job(job["job_id"])
    assert row["status"] == "dispatched"
    assert row["workflow_run_id"]
    run = workflow_store.get_run(row["workflow_run_id"])
    assert run is not None
    assert run["workflow_id"] == workflow_id


def test_one_shot_workflow_schema_change_fails_at_dispatch(test_memory_db_path):
    workflow_id, _ = _publish()
    job = one_shot.register_one_shot_workflow_job(workflow_id, {})

    draft = workflow_store.create_revision(workflow_id)
    workflow_store.update_revision_schema(
        draft["revision_id"],
        {
            "type": "object",
            "properties": {"b": {"type": "string"}},
            "required": ["b"],
        },
    )
    workflow_store.publish_revision(draft["revision_id"])

    one_shot.run_due_one_shot_jobs()
    row = one_shot.get_one_shot_job(job["job_id"])
    assert row["status"] == "failed"
    assert row["error_summary"]
    assert row["workflow_run_id"] is None


# --- YAML validation / ownership --------------------------------------------


def test_validate_jobs_requires_exclusive_target():
    schedule = {"type": "daily", "hour": 1}
    with pytest.raises(ValueError):
        recurring.validate_jobs([{"id": "x", "schedule": schedule}])
    with pytest.raises(ValueError):
        recurring.validate_jobs(
            [
                {
                    "id": "x",
                    "schedule": schedule,
                    "command": "echo hi",
                    "workflow": {"workflow_id": "wf_1"},
                }
            ]
        )
    recurring.validate_jobs(
        [
            {
                "id": "x",
                "schedule": schedule,
                "workflow": {"workflow_id": "wf_1", "inputs": {}},
            }
        ]
    )


def test_merge_revokes_ownership_on_workflow_change():
    from obsidian_ai_hub.scheduler_jobs.recurring import merge_recurring_jobs

    current = [
        {
            "id": "x",
            "enabled": True,
            "schedule": {"type": "daily", "hour": 1},
            "workflow": {"workflow_id": "wf_1", "inputs": {"a": "1"}},
            "agent_source": {"agent_id": "agent-1"},
        }
    ]
    incoming = [
        {
            "id": "x",
            "enabled": True,
            "schedule": {"type": "daily", "hour": 1},
            "workflow": {"workflow_id": "wf_1", "inputs": {"a": "2"}},
        }
    ]
    merged = merge_recurring_jobs(current, incoming)
    assert "agent_source" not in merged[0]


def test_agent_recurring_workflow_tool_inputs_defaults(
    test_memory_db_path, isolated_jobs
):
    from obsidian_ai_hub.agents import registry

    workflow_id, _ = _publish()
    tools = registry.resolve_tools_with_context(
        ["register_recurring_workflow_job"],
        {"agent_id": "agent-1", "session_id": "s1", "run_id": "r1"},
    )
    # ``inputs`` is optional in the schema; invoke without it (schedule only).
    out = json.loads(
        tools[0].invoke(
            {
                "job_id": "wf_job",
                "workflow_id": workflow_id,
                "schedule": {"type": "daily", "hour": 1},
            }
        )
    )
    assert out.get("job_id") == "wf_job", out
    from obsidian_ai_hub.scheduler_jobs import recurring as _recurring

    job = next(j for j in _recurring.load_jobs() if j["id"] == "wf_job")
    assert job["workflow"]["inputs"] == {}


def test_workflow_job_tools_inject_task_context():
    from obsidian_ai_hub.tasks.adapters.registry_tools import TASK_CONTEXT_TOOL_IDS

    assert "register_recurring_workflow_job" in TASK_CONTEXT_TOOL_IDS
    assert "register_one_shot_workflow_job" in TASK_CONTEXT_TOOL_IDS


def test_agent_workflow_tool_rejects_unpublished(test_memory_db_path, isolated_jobs):
    from obsidian_ai_hub.agents import registry

    tools = registry.resolve_tools_with_context(
        ["register_recurring_workflow_job"],
        {"agent_id": "agent-1"},
    )
    out = json.loads(
        tools[0].invoke(
            {
                "job_id": "wf_job",
                "workflow_id": "wf_missing",
                "inputs": {},
                "schedule": {"type": "daily", "hour": 1},
            }
        )
    )
    assert "error" in out
