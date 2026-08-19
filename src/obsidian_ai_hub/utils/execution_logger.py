import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
import traceback
from typing import Any, Dict, List, Optional, Tuple

from obsidian_ai_hub.database import get_db_connection

logger = logging.getLogger(__name__)

# ContextVar to propagate run_id
current_run_id: ContextVar[Optional[str]] = ContextVar("current_run_id", default=None)


def mask_sensitive_dict(d: Any) -> Any:
    """
    Recursively mask sensitive keys in a dictionary or nested structures.
    Sensitive keys are those containing 'token', 'secret', 'password', or 'api_key' as substrings.
    """
    if isinstance(d, dict):
        masked = {}
        for k, v in d.items():
            if any(substring in k.lower() for substring in ("token", "secret", "password", "api_key")):
                masked[k] = "********"
            else:
                masked[k] = mask_sensitive_dict(v)
        return masked
    elif isinstance(d, list):
        return [mask_sensitive_dict(item) for item in d]
    return d


def cleanup_old_logs_now(days: int = 30) -> None:
    """One-shot cleanup of execution/LLM logs older than `days`.

    Opens its own connection so the daily maintenance task can invoke it
    without any in-flight command run. Does not touch task_state.
    """
    conn = get_db_connection()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn.execute("DELETE FROM llm_call_logs WHERE started_at < ?", (cutoff,))
        conn.execute("DELETE FROM command_runs WHERE started_at < ?", (cutoff,))
        conn.commit()
    except Exception as e:
        logger.warning("Failed to clean up old logs: %s", e)
    finally:
        conn.close()


def upsert_task_state(
    task_id: str,
    *,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[Exception] = None,
    now_iso: Optional[str] = None,
) -> None:
    """Upsert a single task_state row for a high-frequency task.

    Three modes:
    - Empty success (no work attempted): increment consecutive_empty_count,
      keep last_processed_at, clear last_error_*.
    - Non-empty success (work attempted): reset consecutive_empty_count to 0;
      update last_processed_at only when processed > 0; refresh latest counts;
      clear last_error_*.
    - Failure (exception raised): update last_error_*; leave
      consecutive_empty_count and last_processed_at unchanged.

    `result` is the dict returned by the command (processed/skipped/failed).
    """
    conn = get_db_connection()
    try:
        now = now_iso or datetime.now(timezone.utc).isoformat()
        processed = int((result or {}).get("processed", 0) or 0)
        skipped = int((result or {}).get("skipped", 0) or 0)
        failed = int((result or {}).get("failed", 0) or 0)
        is_empty = processed == 0 and failed == 0
        is_error = error is not None

        # Current row, used only to derive increments/preserved fields. The
        # write below is a single atomic upsert, so a concurrent first-write
        # cannot raise IntegrityError on the primary key.
        cur = conn.execute("SELECT * FROM task_state WHERE task_id = ?", (task_id,))
        row = cur.fetchone()

        if row is None:
            if is_error:
                consecutive_empty = 0
                last_processed = None
                last_error_at = now
                last_error_msg = str(error)
                last_error_type = type(error).__name__
            elif is_empty:
                consecutive_empty = 1
                last_processed = None
                last_error_at = None
                last_error_msg = None
                last_error_type = None
            else:
                consecutive_empty = 0
                last_processed = now if processed > 0 else None
                last_error_at = None
                last_error_msg = None
                last_error_type = None
        else:
            if is_error:
                consecutive_empty = row["consecutive_empty_count"]
                last_processed = row["last_processed_at"]
                last_error_at = now
                last_error_msg = str(error)
                last_error_type = type(error).__name__
            elif is_empty:
                consecutive_empty = row["consecutive_empty_count"] + 1
                last_processed = row["last_processed_at"]
                last_error_at = None
                last_error_msg = None
                last_error_type = None
            else:
                consecutive_empty = 0
                last_processed = now if processed > 0 else row["last_processed_at"]
                last_error_at = None
                last_error_msg = None
                last_error_type = None

        conn.execute(
            """
            INSERT INTO task_state (
                task_id, last_check_at, consecutive_empty_count,
                last_processed_at, last_error_at, last_error_message, last_error_type,
                processed_count, skipped_count, failed_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                last_check_at = excluded.last_check_at,
                consecutive_empty_count = excluded.consecutive_empty_count,
                last_processed_at = excluded.last_processed_at,
                last_error_at = excluded.last_error_at,
                last_error_message = excluded.last_error_message,
                last_error_type = excluded.last_error_type,
                processed_count = excluded.processed_count,
                skipped_count = excluded.skipped_count,
                failed_count = excluded.failed_count,
                updated_at = excluded.updated_at
            """,
            (
                task_id, now, consecutive_empty,
                last_processed, last_error_at, last_error_msg, last_error_type,
                processed, skipped, failed, now,
            ),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to upsert task state: %s", e)
    finally:
        conn.close()


def suppress_command_run(run_id: str) -> bool:
    """Delete a command run that turned out to be an empty no-op run.

    Removes the command_runs row and, via ON DELETE CASCADE, any child LLM
    call logs. Refuses to delete when LLM call logs exist for the run, since
    that indicates real work happened and the logs must be preserved.

    Returns True when the run was suppressed.
    """
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "SELECT 1 FROM llm_call_logs WHERE run_id = ? LIMIT 1", (run_id,)
        )
        if cur.fetchone() is not None:
            return False
        conn.execute("DELETE FROM command_runs WHERE run_id = ?", (run_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error("Failed to suppress command run: %s", e)
        return False
    finally:
        conn.close()


def list_task_states() -> List[Dict[str, Any]]:
    """Return all task_state rows ordered by most recent check first."""
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "SELECT * FROM task_state ORDER BY last_check_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def start_command_run(run_id: str, command: str, args: Dict[str, Any]) -> None:
    """Logs the start of a command run."""
    conn = get_db_connection()
    try:
        started_at = datetime.now(timezone.utc).isoformat()
        args_json = json.dumps(mask_sensitive_dict(args), ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO command_runs (run_id, command, args_json, started_at, status)
            VALUES (?, ?, ?, ?, 'running')
            """,
            (run_id, command, args_json, started_at),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to start command run: %s", e)
    finally:
        conn.close()


def succeed_command_run(run_id: str, result: Any) -> None:
    """Logs the success of a command run with a summary of the result."""
    conn = get_db_connection()
    try:
        finished_at = datetime.now(timezone.utc).isoformat()
        # Create summary (up to 2000 chars)
        if result is None:
            summary = "No return value"
        else:
            summary = str(result)[:2000]

        conn.execute(
            """
            UPDATE command_runs
            SET finished_at = ?, status = 'succeeded', summary = ?
            WHERE run_id = ?
            """,
            (finished_at, summary, run_id),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to succeed command run: %s", e)
    finally:
        conn.close()


def fail_command_run(run_id: str, exc: Exception) -> None:
    """Logs the failure of a command run with traceback."""
    conn = get_db_connection()
    try:
        finished_at = datetime.now(timezone.utc).isoformat()
        exc_type = type(exc).__name__
        exc_msg = str(exc)
        tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

        conn.execute(
            """
            UPDATE command_runs
            SET finished_at = ?, status = 'failed', exception_type = ?, exception_message = ?, traceback = ?
            WHERE run_id = ?
            """,
            (finished_at, exc_type, exc_msg, tb_str, run_id),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to fail command run: %s", e)
    finally:
        conn.close()


def start_llm_call(
    call_id: str,
    run_id: Optional[str],
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
    prompt: str,
) -> None:
    """Logs the start of an LLM call."""
    conn = get_db_connection()
    try:
        started_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO llm_call_logs (
                call_id, run_id, provider, model, temperature, max_tokens, prompt, started_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running')
            """,
            (call_id, run_id, provider, model, temperature, max_tokens, prompt, started_at),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to start LLM call: %s", e)
    finally:
        conn.close()


def succeed_llm_call(
    call_id: str,
    response: str,
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    total_tokens: Optional[int],
    finish_reason: Optional[str],
) -> None:
    """Logs the success of an LLM call."""
    conn = get_db_connection()
    try:
        finished_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE llm_call_logs
            SET response = ?, prompt_tokens = ?, completion_tokens = ?, total_tokens = ?, finish_reason = ?, finished_at = ?, status = 'succeeded'
            WHERE call_id = ?
            """,
            (response, prompt_tokens, completion_tokens, total_tokens, finish_reason, finished_at, call_id),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to succeed LLM call: %s", e)
    finally:
        conn.close()


def fail_llm_call(call_id: str, exc: Exception) -> None:
    """Logs the failure of an LLM call."""
    conn = get_db_connection()
    try:
        finished_at = datetime.now(timezone.utc).isoformat()
        exc_type = type(exc).__name__
        exc_msg = str(exc)
        tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

        conn.execute(
            """
            UPDATE llm_call_logs
            SET finished_at = ?, status = 'failed', exception_type = ?, exception_message = ?, traceback = ?
            WHERE call_id = ?
            """,
            (finished_at, exc_type, exc_msg, tb_str, call_id),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to fail LLM call: %s", e)
    finally:
        conn.close()


def list_execution_logs(
    kind: Optional[str] = None,
    status: Optional[str] = None,
    command: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    List execution logs (command runs, LLM calls or both) sorted by started_at DESC.
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    conn = get_db_connection()
    try:
        queries = []
        params_runs = []
        params_llm = []

        # Command runs sub-query
        if kind is None or kind == "command":
            conds = []
            if status:
                conds.append("status = ?")
                params_runs.append(status)
            if command:
                conds.append("command LIKE ?")
                params_runs.append(f"%{command}%")
            if from_date:
                conds.append("started_at >= ?")
                params_runs.append(from_date)
            if to_date:
                conds.append("started_at <= ?")
                params_runs.append(to_date)

            where_clause = " WHERE " + " AND ".join(conds) if conds else ""
            cmd_q = f"SELECT run_id AS id, 'command' AS kind, status, command AS name, started_at, finished_at, summary FROM command_runs{where_clause}"
            queries.append((cmd_q, params_runs))

        # LLM call logs sub-query
        if kind is None or kind == "llm":
            conds = []
            if status:
                conds.append("status = ?")
                params_llm.append(status)
            if command:
                conds.append("(provider LIKE ? OR model LIKE ?)")
                params_llm.append(f"%{command}%")
                params_llm.append(f"%{command}%")
            if from_date:
                conds.append("started_at >= ?")
                params_llm.append(from_date)
            if to_date:
                conds.append("started_at <= ?")
                params_llm.append(to_date)

            where_clause = " WHERE " + " AND ".join(conds) if conds else ""
            llm_q = f"SELECT call_id AS id, 'llm' AS kind, status, (provider || '/' || model) AS name, started_at, finished_at, NULL AS summary FROM llm_call_logs{where_clause}"
            queries.append((llm_q, params_llm))

        full_query_parts = []
        all_params = []
        for q_str, q_params in queries:
            full_query_parts.append(q_str)
            all_params.extend(q_params)

        combined_sql = " UNION ALL ".join(full_query_parts)

        data_sql = f"SELECT * FROM ({combined_sql}) ORDER BY started_at DESC LIMIT ? OFFSET ?"
        count_sql = f"SELECT COUNT(*) as total FROM ({combined_sql})"

        cursor = conn.cursor()
        cursor.execute(count_sql, all_params)
        total = cursor.fetchone()["total"]

        cursor.execute(data_sql, all_params + [limit, offset])
        rows = cursor.fetchall()
        items = [dict(row) for row in rows]

        return items, total
    finally:
        conn.close()


def get_command_run_detail(run_id: str) -> Optional[Dict[str, Any]]:
    """Returns details of a command run, including its child LLM calls."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM command_runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if not row:
            return None

        cmd_detail = dict(row)

        # Fetch children (without heavy prompt/response fields to keep detail payload lightweight, or full rows)
        cursor.execute(
            """
            SELECT call_id, provider, model, temperature, max_tokens, prompt_tokens, completion_tokens, total_tokens, finish_reason, started_at, finished_at, status, exception_type, exception_message
            FROM llm_call_logs
            WHERE run_id = ?
            ORDER BY started_at ASC
            """,
            (run_id,),
        )
        children = [dict(r) for r in cursor.fetchall()]
        cmd_detail["llm_calls"] = children

        return cmd_detail
    finally:
        conn.close()


def get_llm_call_detail(call_id: str) -> Optional[Dict[str, Any]]:
    """Returns the full details of an LLM call log."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM llm_call_logs WHERE call_id = ?", (call_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()
