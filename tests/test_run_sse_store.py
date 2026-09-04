"""Unit tests for run-SSE persistence (migration v34 + store extensions)."""

import pytest

from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.coding import store as coding_store
from obsidian_ai_hub.database import get_db_connection


def test_migration_v34_schema():
    conn = get_db_connection()
    cur = conn.execute("PRAGMA user_version;")
    assert cur.fetchone()[0] >= 35

    for table in ("agent_runs", "coding_runs"):
        cur = conn.execute(f"PRAGMA table_info({table});")
        cols = {r["name"] for r in cur.fetchall()}
        for expected in (
            "idempotency_key",
            "idempotency_hash",
            "created_instance_id",
            "worker_instance_id",
        ):
            assert expected in cols, f"{table} missing {expected}"

    for table in ("agent_run_events", "coding_run_events"):
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table,)
        )
        assert cur.fetchone() is not None
        cur = conn.execute(f"PRAGMA table_info({table});")
        cols = {r["name"] for r in cur.fetchall()}
        assert {"event_id", "run_id", "event_type", "payload_json", "created_at"} <= cols


def test_agent_queued_idempotent_start():
    agent = agent_store.create_agent(name="Idem Agent", system_prompt="P")
    session = agent_store.create_session(agent["agent_id"])
    sid = session["session_id"]

    msg1, run1 = agent_store.start_queued_run(
        sid, "hello", idempotency_key="k1", created_instance_id="inst-1"
    )
    assert run1["status"] == "queued"
    assert run1["idempotency_key"] == "k1"

    # Same key + same body replays first run without double save.
    msg2, run2 = agent_store.start_queued_run(
        sid, "hello", idempotency_key="k1", created_instance_id="inst-1"
    )
    assert run2["run_id"] == run1["run_id"]
    assert msg2["message_id"] == msg1["message_id"]
    assert len(agent_store.list_messages(sid)) == 1
    assert len(agent_store.list_runs(sid)) == 1

    # Same key + different body conflicts.
    with pytest.raises(ValueError, match="conflict"):
        agent_store.start_queued_run(
            sid, "different", idempotency_key="k1", created_instance_id="inst-1"
        )


def test_agent_active_run_guard_and_delete_refusal():
    agent = agent_store.create_agent(name="Active Agent", system_prompt="P")
    session = agent_store.create_session(agent["agent_id"])
    sid = session["session_id"]

    agent_store.start_queued_run(sid, "first", created_instance_id="i1")
    with pytest.raises(ValueError, match="active"):
        agent_store.start_queued_run(sid, "second", created_instance_id="i1")

    with pytest.raises(ValueError, match="active"):
        agent_store.delete_session(sid)

    # After terminal transition, new start + delete succeed.
    active = agent_store.get_active_run_for_session(sid)
    assert active is not None
    agent_store.transition_run_status(active["run_id"], "running")
    agent_store.transition_run_status(active["run_id"], "failed", error_message="x", finished=True)
    assert agent_store.get_active_run_for_session(sid) is None
    msg, run = agent_store.start_queued_run(sid, "second", created_instance_id="i1")
    assert run["status"] == "queued"


def test_agent_state_transitions_and_cancel():
    agent = agent_store.create_agent(name="Trans Agent", system_prompt="P")
    session = agent_store.create_session(agent["agent_id"])
    _, run = agent_store.start_queued_run(session["session_id"], "hi")
    rid = run["run_id"]

    # Invalid jump queued -> succeeded rejected.
    with pytest.raises(ValueError, match="not allowed"):
        agent_store.transition_run_status(rid, "succeeded")

    agent_store.transition_run_status(rid, "running")
    cancelled = agent_store.request_cancel_run(rid)
    assert cancelled["status"] == "cancelling"
    # Idempotent cancel.
    assert agent_store.request_cancel_run(rid)["status"] == "cancelling"
    final = agent_store.transition_run_status(rid, "cancelled", finished=True)
    assert final["status"] == "cancelled"
    # Terminal cancel is no-op.
    assert agent_store.request_cancel_run(rid)["status"] == "cancelled"


def test_agent_events_append_replay_and_validation():
    agent = agent_store.create_agent(name="Evt Agent", system_prompt="P")
    session = agent_store.create_session(agent["agent_id"])
    _, run = agent_store.start_queued_run(session["session_id"], "hi")
    rid = run["run_id"]

    with pytest.raises(ValueError, match="Unknown"):
        agent_store.append_run_event(rid, "nope", {})

    e1 = agent_store.append_run_event(rid, "thinking", {"iteration": 1})
    e2 = agent_store.append_run_event(rid, "text_append", {"delta": "hello "})
    e3 = agent_store.append_run_event(rid, "text_append", {"delta": "world"})
    assert e1 < e2 < e3

    all_events = agent_store.list_run_events(rid, after_id=0)
    assert [e["event_id"] for e in all_events] == [e1, e2, e3]
    assert all_events[0]["event_type"] == "thinking"

    tail = agent_store.list_run_events(rid, after_id=e1)
    assert [e["event_id"] for e in tail] == [e2, e3]
    # Client concatenates text_append deltas in id order.
    assert "".join(e["payload"]["delta"] for e in tail) == "hello world"


def test_agent_claim_and_interrupted_recovery():
    agent = agent_store.create_agent(name="Claim Agent", system_prompt="P")
    s1 = agent_store.create_session(agent["agent_id"])
    s2 = agent_store.create_session(agent["agent_id"])
    _, r1 = agent_store.start_queued_run(s1["session_id"], "one", created_instance_id="inst-a")
    _, r2 = agent_store.start_queued_run(s2["session_id"], "two", created_instance_id="inst-a")

    claimed = agent_store.claim_queued_run("worker-1")
    assert claimed is not None
    assert claimed["run_id"] in (r1["run_id"], r2["run_id"])
    assert claimed["status"] == "running"
    assert claimed["worker_instance_id"] == "worker-1"

    # Startup recovery marks other-instance non-terminal runs interrupted.
    count = agent_store.mark_other_instances_interrupted("inst-b")
    assert count >= 1
    for rid in (r1["run_id"], r2["run_id"]):
        assert agent_store.get_run(rid)["status"] in ("running", "interrupted")


def test_agent_status_event_transactional_integrity():
    agent = agent_store.create_agent(name="Txn Agent", system_prompt="P")
    session = agent_store.create_session(agent["agent_id"])
    _, run = agent_store.start_queued_run(session["session_id"], "txn")
    rid = run["run_id"]
    conn = get_db_connection()
    try:
        # Atomic queued -> running + thinking event in one transaction.
        with conn:
            agent_store.transition_run_status(rid, "running", conn=conn)
            agent_store.append_run_event(rid, "thinking", {"iteration": 1}, conn=conn)
        assert agent_store.get_run(rid)["status"] == "running"
        assert len(agent_store.list_run_events(rid, after_id=0)) == 1

        # Failed event append rolls back the status change.
        with pytest.raises(ValueError, match="Unknown"):
            with conn:
                agent_store.transition_run_status(rid, "cancelling", conn=conn)
                agent_store.append_run_event(rid, "bogus", {}, conn=conn)
        assert agent_store.get_run(rid)["status"] == "running"
        assert len(agent_store.list_run_events(rid, after_id=0)) == 1
    finally:
        conn.close()


def test_coding_queued_idempotent_and_guards(tmp_path):
    # Build a minimal coding session without the test_project fixture.
    import subprocess

    from obsidian_ai_hub.database import get_db_connection as _conn

    tmp = tmp_path
    repo = tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "README.md").write_text("# R\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)

    conn = _conn()
    cur = conn.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status, project_path, created_at, updated_at)"
        " VALUES ('sse-proj', 'SSE Proj', 'personal', 'active', ?, datetime('now'), datetime('now'));",
        (str(repo),),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()

    session = coding_store.create_session(
        project_id=pid, backend="codex", repo_path=str(repo), title="S"
    )
    sid = session["session_id"]

    umsg1, run1 = coding_store.start_queued_run(
        sid, "do work", idempotency_key="ck1", created_instance_id="inst-1"
    )
    assert run1["status"] == "queued"

    umsg2, run2 = coding_store.start_queued_run(
        sid, "do work", idempotency_key="ck1", created_instance_id="inst-1"
    )
    assert run2["run_id"] == run1["run_id"]
    assert umsg2["message_id"] == umsg1["message_id"]

    with pytest.raises(ValueError, match="conflict"):
        coding_store.start_queued_run(
            sid, "other work", idempotency_key="ck1", created_instance_id="inst-1"
        )

    with pytest.raises(ValueError, match="active"):
        coding_store.start_queued_run(sid, "second", created_instance_id="inst-1")

    with pytest.raises(ValueError, match="active"):
        coding_store.delete_session(sid)

    active = coding_store.get_active_run_for_session(sid)
    assert active is not None and active["run_id"] == run1["run_id"]

    claimed = coding_store.claim_queued_run("worker-c")
    assert claimed is not None and claimed["status"] == "running"

    cancelled = coding_store.request_cancel_run(claimed["run_id"])
    assert cancelled["status"] == "cancelling"

    e1 = coding_store.append_run_event(
        claimed["run_id"], "orchestrator_start", {"phase": "initial", "phase_turn": 1}
    )
    e2 = coding_store.append_run_event(claimed["run_id"], "text_append", {"delta": "abc"})
    replay = coding_store.list_run_events(claimed["run_id"], after_id=e1)
    assert [e["event_id"] for e in replay] == [e2]
    assert replay[0]["payload"] == {"delta": "abc"}

    with pytest.raises(ValueError, match="Unknown"):
        coding_store.append_run_event(claimed["run_id"], "bogus", {})

    # Invalid transition queued->completed is rejected on a fresh queued run.
    coding_store.transition_run_status(claimed["run_id"], "cancelled", finished=True)
    assert coding_store.get_active_run_for_session(sid) is None
