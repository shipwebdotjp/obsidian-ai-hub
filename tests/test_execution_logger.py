import uuid
from obsidian_ai_hub import memory
from obsidian_ai_hub.utils import execution_logger


def test_mask_sensitive_dict():
    d = {
        "normal_key": "normal_val",
        "api_key": "super_secret_api_key",
        "my_token_value": "secret_token",
        "nested": {
            "password": "my_password",
            "other": 123
        }
    }
    masked = execution_logger.mask_sensitive_dict(d)
    assert masked["normal_key"] == "normal_val"
    assert masked["api_key"] == "********"
    assert masked["my_token_value"] == "********"
    assert masked["nested"]["password"] == "********"
    assert masked["nested"]["other"] == 123


def test_command_run_and_llm_call_logging(test_memory_db_path):
    run_id = str(uuid.uuid4())
    execution_logger.start_command_run(run_id, "test-command", {"param": "val", "token": "abc"})

    # Check it exists and is running
    detail = execution_logger.get_command_run_detail(run_id)
    assert detail is not None
    assert detail["command"] == "test-command"
    assert "********" in detail["args_json"]
    assert detail["status"] == "running"

    # Log LLM call under this run
    call_id = str(uuid.uuid4())
    execution_logger.start_llm_call(call_id, run_id, "openai", "gpt-4", 0.7, 100, "hello prompt")

    # Complete LLM call
    execution_logger.succeed_llm_call(call_id, "hello response", 10, 20, 30, "stop")

    # Succeed command run
    execution_logger.succeed_command_run(run_id, "command success output")

    # Verify detail has children
    detail = execution_logger.get_command_run_detail(run_id)
    assert detail["status"] == "succeeded"
    assert detail["summary"] == "command success output"
    assert len(detail["llm_calls"]) == 1
    assert detail["llm_calls"][0]["call_id"] == call_id
    assert detail["llm_calls"][0]["total_tokens"] == 30

    # Verify unified list
    items, total = execution_logger.list_execution_logs()
    assert total >= 2
    # Unified list items are sorted started_at DESC
    assert items[0]["id"] == run_id or items[0]["id"] == call_id


def test_old_logs_cleanup(test_memory_db_path):
    # Manually insert old log via sqlite connection to verify cleanup
    conn = memory.get_db_connection()
    try:
        # 31 days ago
        from datetime import datetime, timezone, timedelta
        old_time = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        new_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

        conn.execute(
            "INSERT INTO command_runs (run_id, command, args_json, started_at, status) VALUES (?, ?, ?, ?, 'running')",
            ("old-run", "old-cmd", "{}", old_time)
        )
        conn.execute(
            "INSERT INTO command_runs (run_id, command, args_json, started_at, status) VALUES (?, ?, ?, ?, 'running')",
            ("new-run", "new-cmd", "{}", new_time)
        )
        conn.commit()
    finally:
        conn.close()

    # Run a normal write first: it must NOT trigger cleanup
    run_id = str(uuid.uuid4())
    execution_logger.start_command_run(run_id, "trigger-cmd", {})
    items, total = execution_logger.list_execution_logs()
    ids = {item["id"] for item in items}
    assert "old-run" in ids

    # Daily maintenance task performs the cleanup explicitly
    execution_logger.cleanup_old_logs_now(days=30)

    # Check database: old-run should be deleted, new-cmd and trigger-cmd should remain
    items, total = execution_logger.list_execution_logs()
    ids = {item["id"] for item in items}
    assert "old-run" not in ids
    assert "new-run" in ids
    assert run_id in ids
