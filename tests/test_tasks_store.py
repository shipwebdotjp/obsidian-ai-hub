import sqlite3

import pytest

from obsidian_ai_hub.database import (
    get_db_connection,
    run_migration_v44,
    run_migration_v56,
)
from obsidian_ai_hub.tasks import store
from obsidian_ai_hub.tasks.capabilities import get_capability_definitions
from obsidian_ai_hub.utils import config


def test_migration_v44_schema_and_seed():
    conn = get_db_connection()
    try:
        cursor = conn.execute("PRAGMA user_version;")
        assert cursor.fetchone()[0] >= 44

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('task_agent_tasks', 'task_agent_plans', 'task_agent_events', "
            "'task_agent_capabilities');"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert tables == {
            "task_agent_tasks",
            "task_agent_plans",
            "task_agent_events",
            "task_agent_capabilities",
        }

        capabilities = store.list_capabilities(conn=conn)
        assert {c["capability_key"] for c in capabilities} == {
            d.key for d in get_capability_definitions()
        }
        by_key = {c["capability_key"]: c for c in capabilities}
        assert by_key["web_search"]["approval_policy"] == "auto"
        assert by_key["web_search"]["enabled"] is True
        assert by_key["memory_propose"]["approval_policy"] == "plan_required"
        assert by_key["specialist_agent"]["approval_policy"] == "plan_required"
        assert by_key["coding_cli"]["approval_policy"] == "plan_required"
    finally:
        conn.close()


def test_migration_v44_seed_preserves_db_owned_fields():
    conn = get_db_connection()
    try:
        store.update_capability(
            "coding_cli", enabled=False, approval_policy="auto", conn=conn
        )
        run_migration_v44(conn)
        capabilities = store.list_capabilities(conn=conn)
        assert len(capabilities) == len(get_capability_definitions())
        coding_cli = store.get_capability("coding_cli", conn=conn)
        assert coding_cli is not None
        assert coding_cli["enabled"] is False
        assert coding_cli["approval_policy"] == "auto"
        assert coding_cli["adapter_kind"] == "coding"
    finally:
        conn.close()


def test_migration_v56_backfills_workflow_origin(tmp_path):
    conn = sqlite3.connect(tmp_path / "legacy.sqlite3")
    try:
        conn.execute(
            "CREATE TABLE task_agent_tasks ("
            "task_id TEXT PRIMARY KEY, prompt_text TEXT NOT NULL, "
            "status TEXT NOT NULL, created_at TEXT NOT NULL, "
            "updated_at TEXT NOT NULL);"
        )
        conn.execute(
            "INSERT INTO task_agent_tasks VALUES "
            "('task_user', 'summarize', 'queued', 't', 't');"
        )
        conn.execute(
            "INSERT INTO task_agent_tasks VALUES "
            "('task_bridge', 'Workflow run wrun_1 node n (web_search)', "
            "'completed', 't', 't');"
        )
        conn.execute(
            "INSERT INTO task_agent_tasks VALUES "
            "('task_user_lookalike', 'Workflow run failed, investigate', "
            "'queued', 't', 't');"
        )
        run_migration_v56(conn)
        rows = dict(
            conn.execute("SELECT task_id, origin FROM task_agent_tasks;").fetchall()
        )
    finally:
        conn.close()
    assert rows["task_user"] == "user"
    assert rows["task_bridge"] == "workflow"
    # A user prompt that merely starts with the same words is not a bridge.
    assert rows["task_user_lookalike"] == "user"


def test_create_task_validation_and_defaults():
    with pytest.raises(ValueError, match="must not be blank"):
        store.create_task("   ")
    task = store.create_task("Summarize today")
    assert task["task_id"].startswith("task_")
    assert task["status"] == "queued"
    assert task["prompt_text"] == "Summarize today"
    assert task["current_plan_id"] is None
    fetched = store.get_task(task["task_id"])
    assert fetched == task
    assert any(t["task_id"] == task["task_id"] for t in store.list_tasks())


def test_plan_versioning_and_current_plan():
    task = store.create_task("Plan me")
    plan_v1 = store.create_plan(
        task["task_id"], {"purpose": "v1"}, {"coding_cli": "plan_required"}
    )
    assert plan_v1["version"] == 1
    assert plan_v1["status"] == "pending"
    assert plan_v1["plan"] == {"purpose": "v1"}
    plan_v2 = store.create_plan(
        task["task_id"], {"purpose": "v2"}, {"coding_cli": "plan_required"}
    )
    assert plan_v2["version"] == 2
    plans = store.list_plans(task["task_id"])
    assert [p["version"] for p in plans] == [1, 2]
    assert [p["status"] for p in plans] == ["superseded", "pending"]
    updated = store.get_task(task["task_id"])
    assert updated is not None
    assert updated["current_plan_id"] == plan_v2["plan_id"]

    with pytest.raises(FileNotFoundError):
        store.create_plan("task_missing", {}, {})


def _task_in_status(status: str) -> dict:
    task = store.create_task(f"drive to {status}")
    if status == "queued":
        return task
    task = store.claim_task("worker-1", "planning")
    assert task is not None
    if status == "planning":
        return task
    path = {
        "waiting_user": ["waiting_user"],
        "waiting_approval": ["waiting_approval"],
        "ready": ["waiting_approval", "ready"],
        "running": ["running"],
        "waiting_reapproval": ["running", "waiting_reapproval"],
        "cancelling": ["running", "cancelling"],
        "interrupted": ["interrupted"],
    }[status]
    for step in path:
        task = store.transition_task_status(task["task_id"], step)
    return task


def test_full_allowed_transition_map():
    for from_status, targets in store.TASK_ALLOWED_TRANSITIONS.items():
        for to_status in sorted(targets):
            task = _task_in_status(from_status)
            updated = store.transition_task_status(task["task_id"], to_status)
            assert updated["status"] == to_status


def test_list_tasks_excludes_terminal_statuses():
    active = _task_in_status("running")
    completed = _task_in_status("running")
    store.transition_task_status(completed["task_id"], "completed")
    incomplete = _task_in_status("running")
    store.transition_task_status(incomplete["task_id"], "incomplete")

    terminal = set(store.TASK_TERMINAL_STATUSES)
    rows = store.list_tasks(exclude_statuses=terminal)
    ids = {t["task_id"] for t in rows}
    assert active["task_id"] in ids
    assert completed["task_id"] not in ids
    assert incomplete["task_id"] not in ids
    assert store.count_tasks(exclude_statuses=terminal) == len(rows)


def test_non_terminal_filter_service_sentinel():
    from obsidian_ai_hub.web.services.task_agent import (
        NON_TERMINAL_FILTER,
        list_task_agent_tasks,
    )

    active = _task_in_status("running")
    done = _task_in_status("running")
    store.transition_task_status(done["task_id"], "completed")

    items, total = list_task_agent_tasks(status=NON_TERMINAL_FILTER)
    ids = {t["task_id"] for t in items}
    assert active["task_id"] in ids
    assert done["task_id"] not in ids
    assert total == len(items)


def test_task_origin_defaults_and_filtering():
    user_task = store.create_task("user prompt")
    assert user_task["origin"] == "user"
    bridge = store.create_task(
        "Workflow run wrun_x node n (web_search)",
        origin=store.TASK_ORIGIN_WORKFLOW,
    )
    assert bridge["origin"] == "workflow"

    all_ids = {t["task_id"] for t in store.list_tasks()}
    assert {user_task["task_id"], bridge["task_id"]} <= all_ids

    visible = store.list_tasks(exclude_origins={store.TASK_ORIGIN_WORKFLOW})
    visible_ids = {t["task_id"] for t in visible}
    assert user_task["task_id"] in visible_ids
    assert bridge["task_id"] not in visible_ids
    assert store.count_tasks(exclude_origins={store.TASK_ORIGIN_WORKFLOW}) == len(
        visible
    )

    only_bridge = store.list_tasks(origin=store.TASK_ORIGIN_WORKFLOW)
    assert [t["task_id"] for t in only_bridge] == [bridge["task_id"]]

    with pytest.raises(ValueError, match="Unknown task origin"):
        store.create_task("bad origin", origin="elsewhere")


def test_task_list_hides_workflow_bridges():
    from obsidian_ai_hub.web.services.task_agent import list_task_agent_tasks

    visible = store.create_task("visible user task")
    bridge = store.create_task(
        "Workflow run wrun_hidden node n (web_search)",
        origin=store.TASK_ORIGIN_WORKFLOW,
    )
    items, total = list_task_agent_tasks()
    ids = {t["task_id"] for t in items}
    assert visible["task_id"] in ids
    assert bridge["task_id"] not in ids
    assert total == len(items)


def test_representative_forbidden_transitions():
    task = store.create_task("no direct run")
    with pytest.raises(ValueError, match="Illegal task transition"):
        store.transition_task_status(task["task_id"], "running")
    with pytest.raises(ValueError, match="Illegal task transition"):
        store.transition_task_status(task["task_id"], "ready")

    terminal = _task_in_status("running")
    terminal = store.transition_task_status(terminal["task_id"], "completed")
    assert terminal["finished_at"] is not None
    for to_status in ("queued", "running", "cancelled"):
        with pytest.raises(ValueError, match="Illegal task transition"):
            store.transition_task_status(terminal["task_id"], to_status)

    with pytest.raises(FileNotFoundError):
        store.transition_task_status("task_missing", "cancelled")


def test_decide_plan_approve_and_reject():
    task = _task_in_status("planning")
    store.create_plan(task["task_id"], {"purpose": "p"}, {})
    store.transition_task_status(task["task_id"], "waiting_approval")
    approved = store.decide_plan(task["task_id"], "approve")
    assert approved["status"] == "ready"
    plans = store.list_plans(task["task_id"])
    assert plans[-1]["status"] == "approved"
    assert plans[-1]["decided_at"] is not None
    events = store.list_task_events(task["task_id"])
    assert [e["event_type"] for e in events] == ["plan_approved"]
    assert events[0]["payload"]["plan_id"] == plans[-1]["plan_id"]
    with pytest.raises(ValueError, match="already decided"):
        store.decide_plan(task["task_id"], "approve")

    task2 = _task_in_status("planning")
    store.create_plan(task2["task_id"], {"purpose": "p"}, {})
    store.transition_task_status(task2["task_id"], "waiting_approval")
    with pytest.raises(ValueError, match="reason"):
        store.decide_plan(task2["task_id"], "reject")
    with pytest.raises(ValueError, match="reason"):
        store.decide_plan(task2["task_id"], "reject", reason="  ")
    rejected = store.decide_plan(task2["task_id"], "reject", reason="too vague")
    assert rejected["status"] == "queued"
    plans2 = store.list_plans(task2["task_id"])
    assert plans2[-1]["status"] == "rejected"
    assert plans2[-1]["rejection_reason"] == "too vague"
    events2 = store.list_task_events(task2["task_id"])
    assert [e["event_type"] for e in events2] == ["plan_rejected"]
    assert events2[0]["payload"]["reason"] == "too vague"

    with pytest.raises(ValueError, match="Unknown plan decision"):
        store.decide_plan(task2["task_id"], "maybe")


def test_claim_planning_and_execution():
    first = store.create_task("first")
    second = store.create_task("second")
    claimed = store.claim_task("worker-1", "planning")
    assert claimed is not None
    assert claimed["task_id"] == first["task_id"]
    assert claimed["status"] == "planning"
    assert claimed["worker_instance_id"] == "worker-1"
    claimed2 = store.claim_task("worker-1", "planning")
    assert claimed2 is not None
    assert claimed2["task_id"] == second["task_id"]
    assert store.claim_task("worker-1", "planning") is None

    ready = _task_in_status("waiting_approval")
    store.transition_task_status(ready["task_id"], "ready")
    running = store.claim_task("worker-2", "execution")
    assert running is not None
    assert running["task_id"] == ready["task_id"]
    assert running["status"] == "running"
    assert running["started_at"] is not None
    assert store.claim_task("worker-2", "execution") is None

    with pytest.raises(ValueError, match="Unknown claim kind"):
        store.claim_task("worker-1", "invalid")


def test_events_append_only_with_seq():
    task = store.create_task("eventful")
    event_id = store.append_task_event(task["task_id"], "note", {"text": "hello"})
    assert event_id > 0
    store.append_task_event(task["task_id"], "status_changed", {"to": "planning"})
    events = store.list_task_events(task["task_id"])
    assert [e["seq"] for e in events] == [1, 2]
    assert [e["event_type"] for e in events] == ["note", "status_changed"]
    assert events[0]["payload"] == {"text": "hello"}

    with pytest.raises(ValueError, match="Unknown task event type"):
        store.append_task_event(task["task_id"], "bogus", {})
    with pytest.raises(FileNotFoundError):
        store.append_task_event("task_missing", "note", {})


def test_purge_terminal_tasks_only_with_cascade():
    old = _task_in_status("running")
    store.append_task_event(old["task_id"], "note", {"text": "x"})
    store.create_plan(old["task_id"], {"purpose": "p"}, {})
    store.transition_task_status(old["task_id"], "completed")
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE task_agent_tasks SET finished_at = '2000-01-01T00:00:00+00:00' "
            "WHERE task_id = ?;",
            (old["task_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    recent = _task_in_status("running")
    store.transition_task_status(recent["task_id"], "completed")
    active = store.create_task("stays queued")

    assert store.purge_terminal_tasks(retention_days=30) == 1
    assert store.get_task(old["task_id"]) is None
    assert store.list_plans(old["task_id"]) == []
    assert store.list_task_events(old["task_id"]) == []
    assert store.get_task(recent["task_id"]) is not None
    assert store.get_task(active["task_id"]) is not None


def test_redaction_before_persistence(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-test-secret-123")
    task = store.create_task("use sk-test-secret-123 here")
    assert task["prompt_text"] == "use [REDACTED] here"

    plan = store.create_plan(task["task_id"], {"purpose": "sk-test-secret-123"}, {})
    assert "sk-test-secret-123" not in plan["plan"]["purpose"]
    assert plan["plan"] == {"purpose": "[REDACTED]"}

    store.append_task_event(task["task_id"], "note", {"k": "sk-test-secret-123"})
    events = store.list_task_events(task["task_id"])
    assert events[0]["payload"] == {"k": "[REDACTED]"}

    store.transition_task_status(task["task_id"], "planning")
    updated = store.transition_task_status(
        task["task_id"],
        "failed",
        error_summary="failed with sk-test-secret-123",
    )
    assert updated["error_summary"] == "failed with [REDACTED]"

    task2 = store.create_task("second task")
    store.transition_task_status(task2["task_id"], "planning")
    store.transition_task_status(task2["task_id"], "waiting_approval")
    store.create_plan(task2["task_id"], {"purpose": "p"}, {})
    store.decide_plan(task2["task_id"], "reject", reason="bad sk-test-secret-123")
    plans = store.list_plans(task2["task_id"])
    assert plans[-1]["rejection_reason"] == "bad [REDACTED]"


def test_capability_update_validation():
    updated = store.update_capability("coding_cli", enabled=False)
    assert updated["enabled"] is False
    assert updated["approval_policy"] == "plan_required"
    updated = store.update_capability("coding_cli", approval_policy="auto")
    assert updated["approval_policy"] == "auto"

    with pytest.raises(ValueError, match="Nothing to update"):
        store.update_capability("coding_cli")
    with pytest.raises(ValueError, match="Unknown approval policy"):
        store.update_capability("coding_cli", approval_policy="bogus")
    with pytest.raises(FileNotFoundError):
        store.update_capability("ask_user", enabled=False)
    assert store.get_capability("ask_user") is None


def test_mark_tasks_interrupted_only_owned_inflight():
    store.create_task("owned task")
    owned = store.claim_task("worker-9", "planning")
    assert owned is not None
    other = store.create_task("other worker")
    store.transition_task_status(other["task_id"], "planning")
    waiting = store.create_task("waiting approval")
    store.transition_task_status(waiting["task_id"], "planning")
    store.transition_task_status(waiting["task_id"], "waiting_approval")

    # Simulate another owner for `other` via direct claim path.
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE task_agent_tasks SET worker_instance_id = 'worker-8' WHERE task_id = ?;",
            (other["task_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    assert store.mark_tasks_interrupted("worker-9") == 1
    assert store.get_task(owned["task_id"])["status"] == "interrupted"
    assert store.get_task(other["task_id"])["status"] == "planning"
    assert store.get_task(waiting["task_id"])["status"] == "waiting_approval"

    # interrupted returns to queued only explicitly.
    revived = store.transition_task_status(owned["task_id"], "queued")
    assert revived["status"] == "queued"


def test_tables_enforce_foreign_keys():
    conn = get_db_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO task_agent_plans (plan_id, task_id, version, plan_json, "
                "approval_policy_snapshot, status, created_at) "
                "VALUES ('tplan_x', 'task_missing', 1, '{}', '{}', 'pending', 'now');"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO task_agent_events (task_id, seq, event_type, payload_json, created_at) "
                "VALUES ('task_missing', 1, 'note', '{}', 'now');"
            )
    finally:
        conn.close()
