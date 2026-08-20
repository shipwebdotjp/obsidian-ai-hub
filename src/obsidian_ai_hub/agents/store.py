"""AI Agent store for agents, sessions, messages, and runs (SQLite)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, Optional, Sequence

from obsidian_ai_hub.database import get_db_connection


@contextmanager
def auto_connection(
    conn: Optional[sqlite3.Connection] = None,
) -> Generator[tuple[sqlite3.Connection, bool], None, None]:
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True
    try:
        yield conn, close_conn
    finally:
        if close_conn:
            conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_tool_ids(tool_ids: Sequence[str]) -> list[str]:
    from obsidian_ai_hub.agents.registry import TOOL_DEFINITIONS

    valid = []
    for tid in tool_ids:
        if tid not in TOOL_DEFINITIONS:
            raise ValueError(f"Unknown tool ID: '{tid}'")
        if tid not in valid:
            valid.append(tid)
    return valid


def _row_to_agent(row: sqlite3.Row) -> dict[str, Any]:
    tool_ids = []
    if row["tool_ids_json"]:
        try:
            tool_ids = json.loads(row["tool_ids_json"])
        except (json.JSONDecodeError, TypeError):
            tool_ids = []
    return {
        "agent_id": row["agent_id"],
        "name": row["name"],
        "system_prompt": row["system_prompt"],
        "provider": row["provider"],
        "model": row["model"],
        "tool_ids": tool_ids,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_session(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "agent_id": row["agent_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "message_id": row["message_id"],
        "session_id": row["session_id"],
        "sequence": row["sequence"],
        "role": row["role"],
        "content": row["content"],
        "created_at": row["created_at"],
    }


def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
    used_tools = []
    if row["used_tools_json"]:
        try:
            used_tools = json.loads(row["used_tools_json"])
        except (json.JSONDecodeError, TypeError):
            used_tools = []

    created_hitl_run_ids = []
    if row["created_hitl_run_ids_json"]:
        try:
            created_hitl_run_ids = json.loads(row["created_hitl_run_ids_json"])
        except (json.JSONDecodeError, TypeError):
            created_hitl_run_ids = []

    return {
        "run_id": row["run_id"],
        "session_id": row["session_id"],
        "user_message_id": row["user_message_id"],
        "assistant_message_id": row["assistant_message_id"],
        "status": row["status"],
        "used_tools": used_tools,
        "created_hitl_run_ids": created_hitl_run_ids,
        "error_message": row["error_message"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def create_agent(
    name: str,
    system_prompt: str,
    tool_ids: Sequence[str] | None = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    clean_name = (name or "").strip()
    clean_prompt = (system_prompt or "").strip()
    if not clean_name:
        raise ValueError("Agent name must not be empty.")
    if not clean_prompt:
        raise ValueError("System prompt must not be empty.")

    clean_provider = provider.strip() if provider and provider.strip() else None
    clean_model = model.strip() if model and model.strip() else None
    valid_tool_ids = _validate_tool_ids(tool_ids or [])

    agent_id = f"agent_{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    tool_ids_json = json.dumps(valid_tool_ids, ensure_ascii=False)

    with auto_connection(conn) as (active_conn, is_generated):
        try:
            if is_generated:
                with active_conn:
                    active_conn.execute(
                        """
                        INSERT INTO agents (agent_id, name, system_prompt, provider, model, tool_ids_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            agent_id,
                            clean_name,
                            clean_prompt,
                            clean_provider,
                            clean_model,
                            tool_ids_json,
                            now,
                            now,
                        ),
                    )
            else:
                active_conn.execute(
                    """
                    INSERT INTO agents (agent_id, name, system_prompt, provider, model, tool_ids_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent_id,
                        clean_name,
                        clean_prompt,
                        clean_provider,
                        clean_model,
                        tool_ids_json,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise ValueError(f"Agent with name '{clean_name}' already exists.") from e
            raise

        return get_agent(agent_id, conn=active_conn)  # type: ignore[return-value]


def list_agents(conn: Optional[sqlite3.Connection] = None) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute("SELECT * FROM agents ORDER BY created_at DESC;")
        return [_row_to_agent(row) for row in cursor.fetchall()]


def get_agent(agent_id: str, conn: Optional[sqlite3.Connection] = None) -> dict[str, Any] | None:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute("SELECT * FROM agents WHERE agent_id = ?;", (agent_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_agent(row)


def update_agent(
    agent_id: str,
    name: Optional[str] = None,
    system_prompt: Optional[str] = None,
    tool_ids: Optional[Sequence[str]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    with auto_connection(conn) as (active_conn, is_generated):
        existing = get_agent(agent_id, conn=active_conn)
        if not existing:
            raise FileNotFoundError(f"Agent '{agent_id}' not found.")

        clean_name = name.strip() if name is not None else existing["name"]
        if not clean_name:
            raise ValueError("Agent name must not be empty.")

        clean_prompt = (
            system_prompt.strip() if system_prompt is not None else existing["system_prompt"]
        )
        if not clean_prompt:
            raise ValueError("System prompt must not be empty.")

        clean_provider = (
            provider.strip()
            if provider is not None and provider.strip()
            else (None if provider == "" else existing["provider"])
        )
        clean_model = (
            model.strip()
            if model is not None and model.strip()
            else (None if model == "" else existing["model"])
        )

        valid_tool_ids = (
            _validate_tool_ids(tool_ids) if tool_ids is not None else existing["tool_ids"]
        )
        tool_ids_json = json.dumps(valid_tool_ids, ensure_ascii=False)
        now = _now_iso()

        try:
            if is_generated:
                with active_conn:
                    active_conn.execute(
                        """
                        UPDATE agents
                        SET name = ?, system_prompt = ?, provider = ?, model = ?, tool_ids_json = ?, updated_at = ?
                        WHERE agent_id = ?
                        """,
                        (
                            clean_name,
                            clean_prompt,
                            clean_provider,
                            clean_model,
                            tool_ids_json,
                            now,
                            agent_id,
                        ),
                    )
            else:
                active_conn.execute(
                    """
                    UPDATE agents
                    SET name = ?, system_prompt = ?, provider = ?, model = ?, tool_ids_json = ?, updated_at = ?
                    WHERE agent_id = ?
                    """,
                    (
                        clean_name,
                        clean_prompt,
                        clean_provider,
                        clean_model,
                        tool_ids_json,
                        now,
                        agent_id,
                    ),
                )
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise ValueError(f"Agent with name '{clean_name}' already exists.") from e
            raise

        return get_agent(agent_id, conn=active_conn)  # type: ignore[return-value]


def delete_agent(agent_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                cursor = active_conn.execute("DELETE FROM agents WHERE agent_id = ?;", (agent_id,))
                return cursor.rowcount > 0
        else:
            cursor = active_conn.execute("DELETE FROM agents WHERE agent_id = ?;", (agent_id,))
            return cursor.rowcount > 0


def create_session(
    agent_id: str,
    title: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    with auto_connection(conn) as (active_conn, is_generated):
        agent = get_agent(agent_id, conn=active_conn)
        if not agent:
            raise FileNotFoundError(f"Agent '{agent_id}' not found.")

        session_id = f"asess_{uuid.uuid4().hex[:12]}"
        clean_title = title.strip() if title and title.strip() else "新しい会話"
        now = _now_iso()

        if is_generated:
            with active_conn:
                active_conn.execute(
                    """
                    INSERT INTO agent_sessions (session_id, agent_id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, agent_id, clean_title, now, now),
                )
        else:
            active_conn.execute(
                """
                INSERT INTO agent_sessions (session_id, agent_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, agent_id, clean_title, now, now),
            )

        return get_session(session_id, conn=active_conn)  # type: ignore[return-value]


def list_sessions(agent_id: str, conn: Optional[sqlite3.Connection] = None) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute(
            "SELECT * FROM agent_sessions WHERE agent_id = ? ORDER BY updated_at DESC;",
            (agent_id,),
        )
        return [_row_to_session(row) for row in cursor.fetchall()]


def get_session(session_id: str, conn: Optional[sqlite3.Connection] = None) -> dict[str, Any] | None:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute(
            "SELECT * FROM agent_sessions WHERE session_id = ?;", (session_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_session(row)


def delete_session(session_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                cursor = active_conn.execute(
                    "DELETE FROM agent_sessions WHERE session_id = ?;", (session_id,)
                )
                return cursor.rowcount > 0
        else:
            cursor = active_conn.execute(
                "DELETE FROM agent_sessions WHERE session_id = ?;", (session_id,)
            )
            return cursor.rowcount > 0


def list_messages(session_id: str, conn: Optional[sqlite3.Connection] = None) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute(
            "SELECT * FROM agent_messages WHERE session_id = ? ORDER BY sequence ASC;",
            (session_id,),
        )
        return [_row_to_message(row) for row in cursor.fetchall()]


def start_user_run(
    session_id: str,
    content: str,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    clean_content = content.strip() if content else ""
    if not clean_content:
        raise ValueError("Message content must not be empty.")

    with auto_connection(conn) as (active_conn, is_generated):
        session = get_session(session_id, conn=active_conn)
        if not session:
            raise FileNotFoundError(f"Session '{session_id}' not found.")

        now = _now_iso()

        def _execute_transaction():
            cursor = active_conn.execute(
                "SELECT MAX(sequence) FROM agent_messages WHERE session_id = ?;",
                (session_id,),
            )
            max_seq_row = cursor.fetchone()
            next_seq = (
                max_seq_row[0] if max_seq_row and max_seq_row[0] is not None else 0
            ) + 1

            message_id = f"amsg_{uuid.uuid4().hex[:12]}"
            active_conn.execute(
                """
                INSERT INTO agent_messages (message_id, session_id, sequence, role, content, created_at)
                VALUES (?, ?, ?, 'user', ?, ?)
                """,
                (message_id, session_id, next_seq, clean_content, now),
            )

            run_id = f"arun_{uuid.uuid4().hex[:12]}"
            active_conn.execute(
                """
                INSERT INTO agent_runs (
                    run_id, session_id, user_message_id, assistant_message_id, status,
                    used_tools_json, created_hitl_run_ids_json, error_message, started_at, finished_at
                )
                VALUES (?, ?, ?, NULL, 'running', '[]', '[]', NULL, ?, NULL)
                """,
                (run_id, session_id, message_id, now),
            )

            if session["title"] == "新しい会話" and next_seq == 1:
                title_summary = clean_content[:30].replace("\n", " ")
                active_conn.execute(
                    "UPDATE agent_sessions SET title = ?, updated_at = ? WHERE session_id = ?;",
                    (title_summary, now, session_id),
                )
            else:
                active_conn.execute(
                    "UPDATE agent_sessions SET updated_at = ? WHERE session_id = ?;",
                    (now, session_id),
                )

            return message_id, run_id

        if is_generated:
            with active_conn:
                msg_id, run_id = _execute_transaction()
        else:
            msg_id, run_id = _execute_transaction()

        msg = get_message(msg_id, conn=active_conn)
        run = get_run(run_id, conn=active_conn)
        return msg, run  # type: ignore[return-value]


def complete_run(
    run_id: str,
    assistant_content: str,
    used_tools: Sequence[str] | None = None,
    created_hitl_run_ids: Sequence[str] | None = None,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with auto_connection(conn) as (active_conn, is_generated):
        run = get_run(run_id, conn=active_conn)
        if not run:
            raise FileNotFoundError(f"Run '{run_id}' not found.")

        session_id = run["session_id"]
        now = _now_iso()
        tools_list = list(used_tools) if used_tools else []
        hitl_ids = list(created_hitl_run_ids) if created_hitl_run_ids else []

        def _execute_transaction():
            cursor = active_conn.execute(
                "SELECT MAX(sequence) FROM agent_messages WHERE session_id = ?;",
                (session_id,),
            )
            max_seq_row = cursor.fetchone()
            next_seq = (
                max_seq_row[0] if max_seq_row and max_seq_row[0] is not None else 0
            ) + 1

            assistant_msg_id = f"amsg_{uuid.uuid4().hex[:12]}"

            cursor_update = active_conn.execute(
                """
                UPDATE agent_runs
                SET assistant_message_id = ?, status = 'succeeded', used_tools_json = ?,
                    created_hitl_run_ids_json = ?, finished_at = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (
                    assistant_msg_id,
                    json.dumps(tools_list, ensure_ascii=False),
                    json.dumps(hitl_ids, ensure_ascii=False),
                    now,
                    run_id,
                ),
            )
            if cursor_update.rowcount == 0:
                raise ValueError(f"Run '{run_id}' is not in 'running' state.")

            active_conn.execute(
                """
                INSERT INTO agent_messages (message_id, session_id, sequence, role, content, created_at)
                VALUES (?, ?, ?, 'assistant', ?, ?)
                """,
                (assistant_msg_id, session_id, next_seq, assistant_content, now),
            )

            active_conn.execute(
                "UPDATE agent_sessions SET updated_at = ? WHERE session_id = ?;",
                (now, session_id),
            )

            return assistant_msg_id

        if is_generated:
            with active_conn:
                asst_msg_id = _execute_transaction()
        else:
            asst_msg_id = _execute_transaction()

        msg = get_message(asst_msg_id, conn=active_conn)
        updated_run = get_run(run_id, conn=active_conn)
        return msg, updated_run  # type: ignore[return-value]


def fail_run(
    run_id: str,
    error_message: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    with auto_connection(conn) as (active_conn, is_generated):
        run = get_run(run_id, conn=active_conn)
        if not run:
            raise FileNotFoundError(f"Run '{run_id}' not found.")

        now = _now_iso()

        if is_generated:
            with active_conn:
                active_conn.execute(
                    """
                    UPDATE agent_runs
                    SET status = 'failed', error_message = ?, finished_at = ?
                    WHERE run_id = ? AND status = 'running'
                    """,
                    (error_message, now, run_id),
                )
        else:
            active_conn.execute(
                """
                UPDATE agent_runs
                SET status = 'failed', error_message = ?, finished_at = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (error_message, now, run_id),
            )

        return get_run(run_id, conn=active_conn)  # type: ignore[return-value]


def get_message(message_id: str, conn: Optional[sqlite3.Connection] = None) -> dict[str, Any] | None:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute(
            "SELECT * FROM agent_messages WHERE message_id = ?;", (message_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_message(row)


def get_run(run_id: str, conn: Optional[sqlite3.Connection] = None) -> dict[str, Any] | None:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute("SELECT * FROM agent_runs WHERE run_id = ?;", (run_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_run(row)


def list_runs(session_id: str, conn: Optional[sqlite3.Connection] = None) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute(
            "SELECT * FROM agent_runs WHERE session_id = ? ORDER BY started_at ASC;",
            (session_id,),
        )
        return [_row_to_run(row) for row in cursor.fetchall()]
