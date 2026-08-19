import sys
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub import main as main_module
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils import execution_logger
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def loopback_client(monkeypatch, test_memory_db_path, api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


def _run_cli(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["prog"] + argv)
    main_module.main()


EMPTY_RESULT = {"processed": 0, "skipped": 0, "failed": 0, "checked": 0}


def _run_empty_merge_inbox(monkeypatch, times=1):
    for _ in range(times):
        with patch.object(
            main_module.obsidian_inbox_merge, "main", return_value=EMPTY_RESULT
        ):
            _run_cli(monkeypatch, ["--merge-inbox"])


# --- Empty runs: no command_runs, only task_state ---

def test_empty_merge_inbox_creates_no_command_run(monkeypatch, test_memory_db_path):
    _run_empty_merge_inbox(monkeypatch)

    items, total = execution_logger.list_execution_logs(kind="command", command="merge_inbox")
    assert total == 0
    assert items == []

    states = execution_logger.list_task_states()
    assert len(states) == 1
    s = states[0]
    assert s["task_id"] == "merge_inbox"
    assert s["consecutive_empty_count"] == 1
    assert s["processed_count"] == 0
    assert s["last_processed_at"] is None
    assert s["last_error_at"] is None


def test_multiple_empty_runs_update_task_state_without_growth(monkeypatch, test_memory_db_path):
    _run_empty_merge_inbox(monkeypatch, times=3)

    states = execution_logger.list_task_states()
    assert len(states) == 1
    assert states[0]["consecutive_empty_count"] == 3

    items, total = execution_logger.list_execution_logs(kind="command", command="merge_inbox")
    assert total == 0


# --- Non-empty runs: keep command_run and refresh task_state ---

def test_non_empty_merge_inbox_keeps_command_run(monkeypatch, test_memory_db_path):
    _run_empty_merge_inbox(monkeypatch, times=2)

    with patch.object(
        main_module.obsidian_inbox_merge,
        "main",
        return_value={"processed": 2, "skipped": 1, "failed": 0, "checked": 3},
    ):
        _run_cli(monkeypatch, ["--merge-inbox"])

    items, total = execution_logger.list_execution_logs(kind="command", command="merge_inbox")
    assert total == 1
    assert items[0]["status"] == "succeeded"
    assert items[0]["summary"] == str({"processed": 2, "skipped": 1, "failed": 0, "checked": 3})

    states = execution_logger.list_task_states()
    s = states[0]
    assert s["consecutive_empty_count"] == 0
    assert s["processed_count"] == 2
    assert s["skipped_count"] == 1
    assert s["failed_count"] == 0
    assert s["last_processed_at"] is not None


def test_skipped_only_run_treated_as_empty_increments_streak(monkeypatch, test_memory_db_path):
    with patch.object(
        main_module.obsidian_inbox_merge,
        "main",
        return_value={"processed": 0, "skipped": 3, "failed": 0, "checked": 3},
    ):
        _run_cli(monkeypatch, ["--merge-inbox"])

    items, total = execution_logger.list_execution_logs(kind="command", command="merge_inbox")
    assert total == 0

    states = execution_logger.list_task_states()
    assert states[0]["consecutive_empty_count"] == 1
    assert states[0]["skipped_count"] == 3
    assert states[0]["last_processed_at"] is None


# --- Failures: keep failed command_run and record error in task_state ---

def test_failed_merge_inbox_records_error_in_task_state(monkeypatch, test_memory_db_path):
    with patch.object(
        main_module.obsidian_inbox_merge, "main", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError):
            _run_cli(monkeypatch, ["--merge-inbox"])

    items, total = execution_logger.list_execution_logs(kind="command", command="merge_inbox")
    assert total == 1
    assert items[0]["status"] == "failed"

    states = execution_logger.list_task_states()
    s = states[0]
    assert s["last_error_type"] == "RuntimeError"
    assert s["last_error_message"] == "boom"
    assert s["last_error_at"] is not None


def test_failure_does_not_change_consecutive_empty_count(monkeypatch, test_memory_db_path):
    _run_empty_merge_inbox(monkeypatch, times=2)

    with patch.object(
        main_module.obsidian_inbox_merge, "main", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError):
            _run_cli(monkeypatch, ["--merge-inbox"])

    states = execution_logger.list_task_states()
    assert states[0]["consecutive_empty_count"] == 2


def test_success_after_failure_clears_last_error(monkeypatch, test_memory_db_path):
    with patch.object(
        main_module.obsidian_inbox_merge, "main", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError):
            _run_cli(monkeypatch, ["--merge-inbox"])

    with patch.object(
        main_module.obsidian_inbox_merge, "main", return_value=EMPTY_RESULT
    ):
        _run_cli(monkeypatch, ["--merge-inbox"])

    states = execution_logger.list_task_states()
    s = states[0]
    assert s["last_error_at"] is None
    assert s["last_error_message"] is None
    assert s["last_error_type"] is None


# --- suppress_command_run ---

def test_suppress_command_run_deletes_empty_run(test_memory_db_path):
    run_id = str(uuid.uuid4())
    execution_logger.start_command_run(run_id, "merge_inbox", {})
    assert execution_logger.suppress_command_run(run_id) is True
    assert execution_logger.get_command_run_detail(run_id) is None


def test_suppress_command_run_refuses_when_llm_calls_exist(test_memory_db_path):
    run_id = str(uuid.uuid4())
    execution_logger.start_command_run(run_id, "merge_inbox", {})
    call_id = str(uuid.uuid4())
    execution_logger.start_llm_call(call_id, run_id, "openai", "gpt-4", 0.0, 100, "p")

    assert execution_logger.suppress_command_run(run_id) is False
    detail = execution_logger.get_command_run_detail(run_id)
    assert detail is not None
    assert len(detail["llm_calls"]) == 1


# --- cleanup preserves task_state ---

def test_cleanup_old_logs_now_preserves_task_state(test_memory_db_path):
    execution_logger.upsert_task_state(
        "merge_inbox",
        result={"processed": 1, "skipped": 0, "failed": 0},
    )

    conn = get_db_connection()
    try:
        old_time = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        conn.execute(
            "INSERT INTO command_runs (run_id, command, args_json, started_at, status) "
            "VALUES (?, ?, ?, ?, 'running')",
            ("old-run", "old-cmd", "{}", old_time),
        )
        conn.execute(
            "INSERT INTO llm_call_logs (call_id, run_id, provider, model, temperature, max_tokens, prompt, started_at, status) "
            "VALUES (?, ?, ?, ?, 0, 0, 'p', ?, 'running')",
            ("old-call", "old-run", "openai", "gpt-4o-mini", old_time),
        )
        conn.commit()
    finally:
        conn.close()

    execution_logger.cleanup_old_logs_now(days=30)

    items, total = execution_logger.list_execution_logs(kind="command")
    assert total == 0
    assert all(item["id"] != "old-run" for item in items)

    items, total = execution_logger.list_execution_logs(kind="llm")
    assert total == 0
    assert all(item["id"] != "old-call" for item in items)

    states = execution_logger.list_task_states()
    assert len(states) == 1
    assert states[0]["task_id"] == "merge_inbox"
    assert states[0]["processed_count"] == 1


# --- CLI for cleanup ---

def test_cleanup_execution_logs_cli(monkeypatch, test_memory_db_path):
    with patch(
        "obsidian_ai_hub.utils.execution_logger.cleanup_old_logs_now"
    ) as mock_cleanup:
        _run_cli(monkeypatch, ["--cleanup-execution-logs"])
    mock_cleanup.assert_called_once_with(days=30)


# --- merge_inbox.main() integration (real code path) ---

def test_merge_inbox_main_returns_zero_counts_when_inbox_missing(monkeypatch, tmp_path):
    from obsidian_ai_hub import obsidian_inbox_merge

    monkeypatch.setattr(
        obsidian_inbox_merge.config, "INBOX_PATH", tmp_path / "missing_inbox"
    )
    assert obsidian_inbox_merge.main() == EMPTY_RESULT


# --- Web API ---

def test_task_states_api(loopback_client, test_memory_db_path):
    execution_logger.upsert_task_state(
        "merge_inbox",
        result={"processed": 0, "skipped": 0, "failed": 0},
    )

    res = loopback_client.get("/api/v1/task-states")
    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["task_id"] == "merge_inbox"
    assert item["consecutive_empty_count"] == 1
    assert item["last_check_at"]
    assert "processed_count" in item
