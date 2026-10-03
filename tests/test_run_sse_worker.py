"""Tests for run-SSE common helpers, lock, and recovery (plan step 2)."""

from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.runs import events as run_events
from obsidian_ai_hub.runs import manager as run_manager
from obsidian_ai_hub.runs.instance import RunWorkerLock


def test_text_aggregator_bytes_and_time():
    agg = run_events.TextAggregator(max_ms=10_000, max_bytes=10)
    assert agg.add("abc") is None
    flushed = agg.add("defghij")  # 3+7=10 bytes -> flush
    assert flushed == "abcdefghij"

    # Time-based flush with controllable clock.
    now = [0.0]
    agg2 = run_events.TextAggregator(max_ms=250, max_bytes=4096, clock=lambda: now[0])
    assert agg2.add("hello") is None
    now[0] += 0.3
    assert agg2.add(" world") == "hello world"
    assert agg2.flush() is None


def test_sse_format_and_cursor():
    sse = run_events.format_sse(12, {"type": "thinking"})
    assert sse.startswith("id: 12\n")
    assert "data:" in sse
    assert run_events.parse_last_event_id(None) == 0
    assert run_events.parse_last_event_id("") == 0
    assert run_events.parse_last_event_id("7") == 7
    assert run_events.parse_last_event_id("bad") == 0
    assert run_events.parse_last_event_id(-3) == 0
    assert "heartbeat" in run_events.heartbeat_sse()


def test_instance_lock_exclusive(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "w.lock"
    lock1 = RunWorkerLock(path=path)
    assert lock1.acquire() is True
    try:
        assert lock1.is_held() is True
        # Second process contention: child holding the same path must fail.
        code = (
            "import sys; sys.path.insert(0, 'src');"
            "from obsidian_ai_hub.runs.instance import RunWorkerLock;"
            "from pathlib import Path;"
            f"lock = RunWorkerLock(path=Path({str(path)!r}));"
            "sys.exit(0 if lock.acquire() else 1)"
        )
        # Child cannot share the parent's flock; if the parent holds it, the
        # child acquire must fail. Skip assertion on platforms without flock
        # semantics by tolerating either outcome when the child cannot run.
        try:
            proc = subprocess.run([sys.executable, "-c", code], capture_output=True)
            assert proc.returncode != 0
        except OSError:
            pass
    finally:
        lock1.release()
    assert lock1.is_held() is False
    lock2 = RunWorkerLock(path=path)
    assert lock2.acquire() is True
    lock2.release()


def test_startup_recovery_only_other_instances():
    agent = agent_store.create_agent(name="Recovery Agent", system_prompt="P")
    s1 = agent_store.create_session(agent["agent_id"])
    s2 = agent_store.create_session(agent["agent_id"])
    _, r1 = agent_store.start_queued_run(s1["session_id"], "one", created_instance_id="old-inst")
    _, r2 = agent_store.start_queued_run(s2["session_id"], "two", created_instance_id="new-inst")

    counts = run_manager.startup_recovery("new-inst")
    assert counts["agent_interrupted"] >= 1
    assert agent_store.get_run(r1["run_id"])["status"] == "interrupted"
    # Own instance run stays queued.
    assert agent_store.get_run(r2["run_id"])["status"] == "queued"


def test_shutdown_recovery_only_mine():
    agent = agent_store.create_agent(name="Shutdown Agent", system_prompt="P")
    s1 = agent_store.create_session(agent["agent_id"])
    s2 = agent_store.create_session(agent["agent_id"])
    _, r1 = agent_store.start_queued_run(s1["session_id"], "mine", created_instance_id="mine-inst")
    _, r2 = agent_store.start_queued_run(s2["session_id"], "other", created_instance_id="other-inst")

    counts = run_manager.shutdown_recovery("mine-inst")
    assert counts["agent_interrupted"] >= 1
    assert agent_store.get_run(r1["run_id"])["status"] == "interrupted"
    assert agent_store.get_run(r2["run_id"])["status"] == "queued"
