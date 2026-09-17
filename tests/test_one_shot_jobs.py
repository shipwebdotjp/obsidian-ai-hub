"""One-shot Job operation-scenario contract tests.

Covers the irreversible-operation contract for one-shot jobs
(SQLite queue write + exactly-once OS command launch):

| Stage | Source of truth / ID | Persisted | On stop | Side effect |
| --- | --- | --- | --- | --- |
| Agent register | Pydantic input, trusted Agent context, `job_id` | `queued` job | invalid command is not stored | SQLite write |
| runner claim | due `queued` row | `running` | claim race does not execute | none |
| execute | stored command | exit code, output, terminal state | non-zero is `failed`, crash leftovers are `interrupted` | OS command launched once |
| cancel/retain | `job_id` | `cancelled`, 30-day terminal retention | post-`running` cancel refused | none |

All tests use the isolated per-test SQLite DB (pytest fixtures) and a fake
command executor, so no real subprocess or production data is touched.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from obsidian_ai_hub.scheduler_jobs import one_shot


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _ok_executor(stdout="hello"):
    calls = []

    def run(args, cwd=None):
        calls.append((list(args), cwd))
        return _Proc(0, stdout, "")

    run.calls = calls
    return run


def test_register_claim_execute_once_with_fake_executor(test_memory_db_path):
    """Agent tool register -> atomic claim -> exactly-once run -> result row."""
    from obsidian_ai_hub.agents import registry

    tools = registry.resolve_tools_with_context(
        ["register_one_shot_job"],
        {"agent_id": "agent-1", "session_id": "sess-1", "run_id": "run-1"},
    )
    out = json.loads(tools[0].invoke({"command": "printf hi"}))
    assert out["status"] == "queued"
    job_id = out["job_id"]

    row = one_shot.get_one_shot_job(job_id)
    assert row["status"] == "queued"
    assert row["agent_id"] == "agent-1"
    assert row["session_id"] == "sess-1"
    assert row["run_id"] == "run-1"

    executor = _ok_executor()
    finished = one_shot.run_due_one_shot_jobs(executor=executor)
    assert [j["job_id"] for j in finished] == [job_id]
    assert len(executor.calls) == 1
    assert executor.calls[0][0] == ["printf", "hi"]

    done = one_shot.get_one_shot_job(job_id)
    assert done["status"] == "succeeded"
    assert done["exit_code"] == 0
    assert done["segments"][0]["stdout"] == "hello"
    assert done["finished_at"] is not None

    # Second cycle never re-runs a terminal job (at-most-once).
    assert one_shot.run_due_one_shot_jobs(executor=executor) == []
    assert len(executor.calls) == 1


def test_claim_race_executes_once(test_memory_db_path):
    job = one_shot.register_one_shot_job("printf hi")
    first = one_shot.claim_due_jobs()
    assert [j["job_id"] for j in first] == [job["job_id"]]
    # A concurrent claimant sees nothing to run.
    assert one_shot.claim_due_jobs() == []


def test_future_run_at_not_due_jst_normalized_and_past_immediate(test_memory_db_path):
    now = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)
    future = now + timedelta(hours=1)

    job = one_shot.register_one_shot_job("printf future", run_at=future, now=now)
    assert one_shot.claim_due_jobs(now=now) == []
    claimed = one_shot.claim_due_jobs(now=future + timedelta(seconds=1))
    assert [j["job_id"] for j in claimed] == [job["job_id"]]

    # Naive datetime input is interpreted as JST and stored as UTC.
    jst_job = one_shot.register_one_shot_job(
        "printf jst", run_at=datetime(2026, 9, 18, 10, 0, 0), now=now
    )
    assert jst_job["run_at_utc"] == "2026-09-18T01:00:00+00:00"

    # Past datetimes are kept so they run on the next cycle.
    past_job = one_shot.register_one_shot_job(
        "printf past", run_at="2020-01-01T00:00:00+00:00", now=now
    )
    assert past_job["run_at_utc"] == "2020-01-01T00:00:00+00:00"
    assert any(
        j["job_id"] == past_job["job_id"] for j in one_shot.claim_due_jobs(now=now)
    )


def test_invalid_command_not_persisted(test_memory_db_path):
    with pytest.raises(ValueError):
        one_shot.register_one_shot_job("cd /tmp")
    with pytest.raises(ValueError):
        one_shot.register_one_shot_job("echo 'unclosed")
    with pytest.raises(ValueError):
        one_shot.register_one_shot_job("   ")

    items, total = one_shot.list_one_shot_jobs()
    assert total == 0
    assert items == []


def test_nonzero_exit_is_failed_with_summary(test_memory_db_path):
    job = one_shot.register_one_shot_job("printf no && printf never")

    def failing(args, cwd=None):
        return _Proc(3, "out", "boom")

    (done,) = one_shot.run_due_one_shot_jobs(executor=failing)
    assert done["job_id"] == job["job_id"]
    assert done["status"] == "failed"
    assert done["exit_code"] == 3
    assert "3" in (done["error_summary"] or "")
    assert done["segments"][0]["stderr"] == "boom"


def test_segments_run_in_order_and_stop_on_first_failure(test_memory_db_path):
    one_shot.register_one_shot_job("cd /tmp && printf a && printf b")
    calls = []

    def run(args, cwd=None):
        calls.append((list(args), cwd))
        if args == ["printf", "a"]:
            return _Proc(1, "", "a failed")
        return _Proc(0, "b", "")

    (done,) = one_shot.run_due_one_shot_jobs(executor=run)
    assert done["status"] == "failed"
    # cd applies to later segments; execution stops after the failing segment.
    assert calls == [(["printf", "a"], "/tmp")]
    assert len(done["segments"]) == 1


def test_executor_exception_is_failed_not_retried(test_memory_db_path):
    one_shot.register_one_shot_job("printf hi")

    def raising(args, cwd=None):
        raise OSError("spawn failed")

    (done,) = one_shot.run_due_one_shot_jobs(executor=raising)
    assert done["status"] == "failed"
    assert "spawn failed" in (done["error_summary"] or "")


def test_output_truncated_at_limit(test_memory_db_path):
    one_shot.register_one_shot_job("printf big")
    big = "x" * (one_shot.MAX_OUTPUT_CHARS + 100)

    (done,) = one_shot.run_due_one_shot_jobs(executor=_ok_executor(stdout=big))
    assert done["status"] == "succeeded"
    assert done["output_truncated"] is True
    assert len(done["segments"][0]["stdout"]) < len(big)
    assert "truncated" in done["segments"][0]["stdout"]


def test_cancel_only_queued(test_memory_db_path):
    job = one_shot.register_one_shot_job("printf hi")
    cancelled = one_shot.cancel_one_shot_job(job["job_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["finished_at"] is not None

    with pytest.raises(ValueError):
        one_shot.cancel_one_shot_job(job["job_id"])

    running = one_shot.register_one_shot_job("printf hi")
    one_shot.claim_due_jobs()
    with pytest.raises(ValueError):
        one_shot.cancel_one_shot_job(running["job_id"])

    with pytest.raises(LookupError):
        one_shot.cancel_one_shot_job("missing")

    # Cancelled jobs are never executed.
    executor = _ok_executor()
    assert one_shot.run_due_one_shot_jobs(executor=executor) == []
    assert executor.calls == []


def test_restart_marks_running_interrupted_without_retry(test_memory_db_path):
    doomed = one_shot.register_one_shot_job("printf doomed")
    one_shot.claim_due_jobs()
    assert one_shot.mark_interrupted_orphans() == 1

    row = one_shot.get_one_shot_job(doomed["job_id"])
    assert row["status"] == "interrupted"
    assert row["finished_at"] is not None

    # Interrupted jobs are never auto re-executed.
    executor = _ok_executor()
    assert one_shot.run_due_one_shot_jobs(executor=executor) == []
    assert executor.calls == []

    # But queued jobs still run after a restart.
    queued = one_shot.register_one_shot_job("printf ok")
    (done,) = one_shot.run_due_one_shot_jobs(executor=executor)
    assert done["job_id"] == queued["job_id"]
    assert done["status"] == "succeeded"


def test_terminal_rows_pruned_after_30_days(test_memory_db_path):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=31)

    for status in ("succeeded", "failed", "cancelled", "interrupted"):
        row = one_shot.register_one_shot_job(f"printf {status}")
        if status == "cancelled":
            one_shot.cancel_one_shot_job(row["job_id"], now=old)
        else:
            claimed = one_shot.claim_due_jobs()
            assert claimed
            one_shot.execute_claimed_job(claimed[0], executor=_ok_executor())
            # Backdate the terminal row to simulate age.
            from obsidian_ai_hub.database import get_db_connection

            conn = get_db_connection()
            try:
                conn.execute(
                    "UPDATE one_shot_jobs SET status=?, finished_at=? WHERE job_id=?",
                    (status, old.isoformat(), row["job_id"]),
                )
                conn.commit()
            finally:
                conn.close()

    recent = one_shot.register_one_shot_job("printf recent")
    one_shot.cancel_one_shot_job(recent["job_id"], now=now)

    assert one_shot.prune_expired_one_shot_jobs(now=now) == 4
    remaining, _ = one_shot.list_one_shot_jobs()
    assert [r["job_id"] for r in remaining] == [recent["job_id"]]


def test_list_unfinished_first_then_history(test_memory_db_path):
    done = one_shot.register_one_shot_job("printf done")
    one_shot.run_due_one_shot_jobs(executor=_ok_executor())
    one_shot.register_one_shot_job("printf queued")

    items, total = one_shot.list_one_shot_jobs()
    assert total == 2
    assert items[0]["status"] == "queued"
    assert items[1]["job_id"] == done["job_id"]


def test_tool_trusted_source_and_spoof_rejected(test_memory_db_path):
    from obsidian_ai_hub.agents import registry

    assert "register_one_shot_job" in registry.TOOL_DEFINITIONS
    assert any(
        t["tool_id"] == "register_one_shot_job" for t in registry.list_available_tools()
    )

    tools = registry.resolve_tools_with_context(
        ["register_one_shot_job"],
        {"agent_id": "a", "session_id": "s", "run_id": "r"},
    )
    out = json.loads(tools[0].invoke({"command": "printf hi"}))
    row = one_shot.get_one_shot_job(out["job_id"])
    assert (row["agent_id"], row["session_id"], row["run_id"]) == ("a", "s", "r")

    # Agent inputs cannot spoof the registration source (extra=forbid).
    with pytest.raises(Exception):
        tools[0].invoke({"command": "printf hi", "agent_id": "evil"})

    # Invalid run_at is rejected without persisting (tool returns error JSON).
    bad = json.loads(tools[0].invoke({"command": "printf hi", "run_at": "not-a-date"}))
    assert "error" in bad


def test_capability_derived_with_plan_required_default():
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

    caps = {d.key: d for d in get_capability_definitions()}
    cap = caps["register_one_shot_job"]
    assert cap.adapter_kind == "registry_tool"
    assert cap.default_approval_policy == "plan_required"

    from obsidian_ai_hub.tasks.capability_schemas import (
        resolve_json_schema,
        validate_capability_inputs,
    )

    schema = resolve_json_schema("register_one_shot_job")
    assert "command" in schema["properties"]
    validated = validate_capability_inputs(
        "register_one_shot_job", {"command": "printf hi"}
    )
    assert validated["command"] == "printf hi"


def test_full_runner_cycle_recurring_and_one_shot(monkeypatch, tmp_path, test_memory_db_path):
    """job_runner cycle: due recurring job runs + due one-shot runs once."""
    from datetime import datetime as _dt

    from obsidian_ai_hub.scheduler_jobs import recurring
    from obsidian_ai_hub import job_runner

    monkeypatch.setattr(recurring, "TEST_JOB_FILE", tmp_path / "jobs.test.yml")
    monkeypatch.setattr(recurring, "LOCAL_JOB_FILE", tmp_path / "jobs.test.yml")
    monkeypatch.setattr(recurring, "DEFAULT_JOB_FILE", tmp_path / "jobs.test.yml")
    monkeypatch.setattr(recurring, "STATE_FILE", tmp_path / "last_run.json")
    monkeypatch.setattr(recurring, "LOCK_FILE", tmp_path / ".job-config.lock")
    monkeypatch.setattr(recurring, "RUNNER_LOCK_FILE", tmp_path / ".job-runner.lock")

    now = _dt(2026, 9, 17, 10, 0, 30)
    recurring.atomic_write_yaml(
        tmp_path / "jobs.test.yml",
        [
            {
                "id": "every-minute",
                "enabled": True,
                "schedule": {"type": "minutely", "second": 0},
                "command": "printf recurring",
            }
        ],
    )
    recurring.save_state({"every-minute": _dt(2026, 9, 17, 9, 59, 0)})

    one_shot.register_one_shot_job("printf once")

    ran_commands = []
    monkeypatch.setattr(
        recurring, "run_command", lambda cmd: ran_commands.append(cmd)
    )
    real_run = one_shot._default_executor
    monkeypatch.setattr(
        one_shot, "_default_executor", lambda args, cwd=None: _Proc(0, "once", "")
    )
    try:
        result = job_runner.run_cycle(now=now)
    finally:
        monkeypatch.setattr(one_shot, "_default_executor", real_run)

    assert result["recurring"] == ["every-minute"]
    assert ran_commands == ["printf recurring"]
    assert len(result["one_shot"]) == 1
    done = one_shot.get_one_shot_job(result["one_shot"][0])
    assert done["status"] == "succeeded"
    assert done["segments"][0]["stdout"] == "once"

    state = recurring.load_state()
    assert state["every-minute"] == now


def test_cancel_loses_race_to_claim(test_memory_db_path, monkeypatch):
    """If the runner claims between cancel's SELECT and UPDATE, cancel fails.

    The UPDATE rowcount guard must prevent a phantom cancellation of a
    running job (web cancel vs runner process race).
    """
    from obsidian_ai_hub.database import get_db_connection as real_connect

    job = one_shot.register_one_shot_job("printf hi")

    real_conn = real_connect()

    class FlippingConn:
        """Proxy that flips the row to running right after cancel's SELECT."""

        def __init__(self, conn):
            self._conn = conn
            self._flipped = False

        def execute(self, sql, params=()):
            cur = self._conn.execute(sql, params)
            if not self._flipped and "SELECT status FROM one_shot_jobs" in sql:
                self._flipped = True
                # Commit immediately: in production the racing claim runs on a
                # separate connection, so it is not rolled back by cancel's
                # own failed UPDATE below.
                self._conn.execute(
                    "UPDATE one_shot_jobs SET status='running', started_at=? WHERE job_id=?",
                    ("2026-09-17T00:00:00+00:00", job["job_id"]),
                )
                self._conn.commit()
            return cur

        def commit(self):
            return self._conn.commit()

        def close(self):
            return self._conn.close()

    monkeypatch.setattr(one_shot, "get_db_connection", lambda: FlippingConn(real_conn))
    with pytest.raises(ValueError, match="Only queued jobs"):
        one_shot.cancel_one_shot_job(job["job_id"])

    check = real_connect()
    try:
        status = check.execute(
            "SELECT status FROM one_shot_jobs WHERE job_id = ?", (job["job_id"],)
        ).fetchone()["status"]
        assert status == "running"
    finally:
        check.close()
