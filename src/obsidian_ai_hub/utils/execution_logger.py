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


def cleanup_old_logs(conn) -> None:
    """
    Deletes logs older than 30 days based on their started_at timestamp.
    First deletes LLM logs, then command logs.
    """
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        # Delete LLM call logs first
        conn.execute("DELETE FROM llm_call_logs WHERE started_at < ?", (cutoff,))
        # Then delete command runs
        conn.execute("DELETE FROM command_runs WHERE started_at < ?", (cutoff,))
    except Exception as e:
        logger.warning("Failed to clean up old logs: %s", e)


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
        cleanup_old_logs(conn)
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
        cleanup_old_logs(conn)
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
        cleanup_old_logs(conn)
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
        cleanup_old_logs(conn)
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
        cleanup_old_logs(conn)
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
        cleanup_old_logs(conn)
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
