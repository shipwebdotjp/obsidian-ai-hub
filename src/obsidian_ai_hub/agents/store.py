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


def _normalize_advanced_params(raw: Any) -> dict[str, Any]:
    """Normalize user-supplied advanced_params to the stored shape.

    Stored shape: {"max_tokens": int, "reasoning": {"effort": str}}
    No range checks; only structural sanitization. Empty/invalid values are dropped.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    # max_tokens: accept int-like value
    if "max_tokens" in raw:
        val = raw["max_tokens"]
        if val is not None and val != "":
            try:
                # Allow string numbers from JSON/form
                iv = int(val)  # type: ignore[arg-type]
                out["max_tokens"] = iv
            except (ValueError, TypeError):
                # Invalid value: drop silently (API validation will have rejected
                # non-int via Pydantic if sent strictly; this is for loose storage)
                pass
    # reasoning.effort: free text in phase 1
    if "reasoning" in raw and isinstance(raw["reasoning"], dict):
        effort = raw["reasoning"].get("effort")
        if isinstance(effort, str):
            clean = effort.strip()
            if clean:
                out["reasoning"] = {"effort": clean}
    # Also accept flat reasoning_effort for backward/looser input shape
    elif "reasoning_effort" in raw and isinstance(raw["reasoning_effort"], str):
        clean = raw["reasoning_effort"].strip()
        if clean:
            out["reasoning"] = {"effort": clean}
    return out


def _advanced_params_from_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        raw_json = row["advanced_params_json"]  # type: ignore[index]
    except (IndexError, KeyError, ValueError):
        return {}
    if not raw_json:
        return {}
    try:
        parsed = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    normalized = _normalize_advanced_params(parsed)
    # If stored value was already normalized, return as-is but ensure shape
    # If raw_json contained extra keys, normalized will have dropped them
    return normalized


def _advanced_params_to_json(params: Any) -> str:
    normalized = _normalize_advanced_params(params if params is not None else {})
    return json.dumps(normalized, ensure_ascii=False)


def _row_to_agent(row: sqlite3.Row) -> dict[str, Any]:
    tool_ids = []
    if row["tool_ids_json"]:
        try:
            tool_ids = json.loads(row["tool_ids_json"])
        except (json.JSONDecodeError, TypeError):
            tool_ids = []
    advanced_params = _advanced_params_from_row(row)
    return {
        "agent_id": row["agent_id"],
        "name": row["name"],
        "system_prompt": row["system_prompt"],
        "provider": row["provider"],
        "model": row["model"],
        "tool_ids": tool_ids,
        "advanced_params": advanced_params,
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
    attachments: list[dict[str, Any]] = []
    # attachments_json added in v24; tolerate missing column on pre-migration rows
    try:
        raw = row["attachments_json"]  # type: ignore[index]
    except (IndexError, KeyError, ValueError):
        raw = None
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                attachments = [item for item in parsed if isinstance(item, dict)]
        except (json.JSONDecodeError, TypeError):
            attachments = []
    return {
        "message_id": row["message_id"],
        "session_id": row["session_id"],
        "sequence": row["sequence"],
        "role": row["role"],
        "content": row["content"],
        "attachments": attachments,
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

    tool_calls: list[dict[str, Any]] = []
    # tool_calls_json added in v22; tolerate missing column on pre-migration rows
    try:
        raw = row["tool_calls_json"]  # type: ignore[index]
    except (IndexError, KeyError, ValueError):
        raw = None
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                tool_calls = parsed
        except (json.JSONDecodeError, TypeError):
            tool_calls = []

    return {
        "run_id": row["run_id"],
        "session_id": row["session_id"],
        "user_message_id": row["user_message_id"],
        "assistant_message_id": row["assistant_message_id"],
        "status": row["status"],
        "used_tools": used_tools,
        "created_hitl_run_ids": created_hitl_run_ids,
        "tool_calls": tool_calls,
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
    advanced_params: dict[str, Any] | None = None,
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
    advanced_params_json = _advanced_params_to_json(advanced_params)

    with auto_connection(conn) as (active_conn, is_generated):
        try:
            if is_generated:
                with active_conn:
                    try:
                        active_conn.execute(
                            """
                            INSERT INTO agents (agent_id, name, system_prompt, provider, model, tool_ids_json, advanced_params_json, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                agent_id,
                                clean_name,
                                clean_prompt,
                                clean_provider,
                                clean_model,
                                tool_ids_json,
                                advanced_params_json,
                                now,
                                now,
                            ),
                        )
                    except sqlite3.OperationalError as e:
                        if "no such column: advanced_params_json" in str(e):
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
                            raise
            else:
                try:
                    active_conn.execute(
                        """
                        INSERT INTO agents (agent_id, name, system_prompt, provider, model, tool_ids_json, advanced_params_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            agent_id,
                            clean_name,
                            clean_prompt,
                            clean_provider,
                            clean_model,
                            tool_ids_json,
                            advanced_params_json,
                            now,
                            now,
                        ),
                    )
                except sqlite3.OperationalError as e:
                    if "no such column: advanced_params_json" in str(e):
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
                        raise
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
    advanced_params: Optional[dict[str, Any]] = None,
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
        # advanced_params: None means keep existing; otherwise normalize and store
        if advanced_params is None:
            advanced_params_norm = existing.get("advanced_params", {})
        else:
            advanced_params_norm = _normalize_advanced_params(advanced_params)
        advanced_params_json = json.dumps(advanced_params_norm, ensure_ascii=False)
        now = _now_iso()

        try:
            if is_generated:
                with active_conn:
                    try:
                        active_conn.execute(
                            """
                            UPDATE agents
                            SET name = ?, system_prompt = ?, provider = ?, model = ?, tool_ids_json = ?, advanced_params_json = ?, updated_at = ?
                            WHERE agent_id = ?
                            """,
                            (
                                clean_name,
                                clean_prompt,
                                clean_provider,
                                clean_model,
                                tool_ids_json,
                                advanced_params_json,
                                now,
                                agent_id,
                            ),
                        )
                    except sqlite3.OperationalError as e:
                        if "no such column: advanced_params_json" in str(e):
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
                            raise
            else:
                try:
                    active_conn.execute(
                        """
                        UPDATE agents
                        SET name = ?, system_prompt = ?, provider = ?, model = ?, tool_ids_json = ?, advanced_params_json = ?, updated_at = ?
                        WHERE agent_id = ?
                        """,
                        (
                            clean_name,
                            clean_prompt,
                            clean_provider,
                            clean_model,
                            tool_ids_json,
                            advanced_params_json,
                            now,
                            agent_id,
                        ),
                    )
                except sqlite3.OperationalError as e:
                    if "no such column: advanced_params_json" in str(e):
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
                        raise
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
    attachments: Optional[Sequence[dict[str, Any]]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    clean_content = content.strip() if content else ""
    attachments_list: list[dict[str, Any]] = []
    if attachments:
        for item in attachments:
            if isinstance(item, dict):
                attachments_list.append(item)
        if attachments_list:
            try:
                attachments_json = json.dumps(attachments_list, ensure_ascii=False)
            except (TypeError, ValueError):
                attachments_json = "[]"
        else:
            attachments_json = "[]"
    else:
        attachments_json = "[]"
    # Empty user text is allowed only when at least one attachment is present.
    if not clean_content and not attachments_list:
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
            try:
                active_conn.execute(
                    """
                    INSERT INTO agent_messages (message_id, session_id, sequence, role, content, attachments_json, created_at)
                    VALUES (?, ?, ?, 'user', ?, ?, ?)
                    """,
                    (message_id, session_id, next_seq, clean_content, attachments_json, now),
                )
            except sqlite3.OperationalError as e:
                if "no such column: attachments_json" in str(e):
                    active_conn.execute(
                        """
                        INSERT INTO agent_messages (message_id, session_id, sequence, role, content, created_at)
                        VALUES (?, ?, ?, 'user', ?, ?)
                        """,
                        (message_id, session_id, next_seq, clean_content, now),
                    )
                else:
                    raise

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
                # Empty user text (image-only) gets a placeholder title so the
                # session does not keep the default "新しい会話" label.
                title_source = clean_content or "画像を送りました"
                title_summary = title_source[:30].replace("\n", " ")
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
    tool_calls: Sequence[dict[str, Any]] | None = None,
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
        tool_calls_list = list(tool_calls) if tool_calls else []
        tool_calls_json = json.dumps(tool_calls_list, ensure_ascii=False)

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

            active_conn.execute(
                """
                INSERT INTO agent_messages (message_id, session_id, sequence, role, content, created_at)
                VALUES (?, ?, ?, 'assistant', ?, ?)
                """,
                (assistant_msg_id, session_id, next_seq, assistant_content, now),
            )

            # tool_calls_json column added in v22; fall back gracefully on old DBs
            try:
                cursor_update = active_conn.execute(
                    """
                    UPDATE agent_runs
                    SET assistant_message_id = ?, status = 'succeeded', used_tools_json = ?,
                        created_hitl_run_ids_json = ?, tool_calls_json = ?, finished_at = ?
                    WHERE run_id = ? AND status = 'running'
                    """,
                    (
                        assistant_msg_id,
                        json.dumps(tools_list, ensure_ascii=False),
                        json.dumps(hitl_ids, ensure_ascii=False),
                        tool_calls_json,
                        now,
                        run_id,
                    ),
                )
            except sqlite3.OperationalError as e:
                if "no such column: tool_calls_json" in str(e):
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
                else:
                    raise
            if cursor_update.rowcount == 0:
                raise ValueError(f"Run '{run_id}' is not in 'running' state.")

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


# --- Prompt Template Store ---


def _row_to_template(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "template_id": row["template_id"],
        "agent_id": row["agent_id"],
        "name": row["name"],
        "content": row["content"],
        "display_order": row["display_order"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_prompt_templates(
    agent_id: str, conn: Optional[sqlite3.Connection] = None
) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        # Verify agent exists; if not, return empty (route will handle 404 separately)
        cursor = active_conn.execute(
            "SELECT * FROM agent_prompt_templates WHERE agent_id = ? ORDER BY display_order ASC, created_at ASC;",
            (agent_id,),
        )
        return [_row_to_template(row) for row in cursor.fetchall()]


def get_prompt_template(
    template_id: str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any] | None:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute(
            "SELECT * FROM agent_prompt_templates WHERE template_id = ?;",
            (template_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_template(row)


def create_prompt_template(
    agent_id: str,
    name: str,
    content: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    clean_name = (name or "").strip()
    clean_content = (content or "").strip()
    if not clean_name:
        raise ValueError("Template name must not be empty.")
    if not clean_content:
        raise ValueError("Template content must not be empty.")

    with auto_connection(conn) as (active_conn, is_generated):
        agent = get_agent(agent_id, conn=active_conn)
        if not agent:
            raise FileNotFoundError(f"Agent '{agent_id}' not found.")

        cursor = active_conn.execute(
            "SELECT COALESCE(MAX(display_order), -1) + 1 FROM agent_prompt_templates WHERE agent_id = ?;",
            (agent_id,),
        )
        next_order = cursor.fetchone()[0]
        template_id = f"atmpl_{uuid.uuid4().hex[:12]}"
        now = _now_iso()

        def _insert():
            active_conn.execute(
                """
                INSERT INTO agent_prompt_templates (template_id, agent_id, name, content, display_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (template_id, agent_id, clean_name, clean_content, next_order, now, now),
            )

        if is_generated:
            with active_conn:
                _insert()
        else:
            _insert()

        return get_prompt_template(template_id, conn=active_conn)  # type: ignore[return-value]


def update_prompt_template(
    template_id: str,
    name: Optional[str] = None,
    content: Optional[str] = None,
    display_order: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    with auto_connection(conn) as (active_conn, is_generated):
        existing = get_prompt_template(template_id, conn=active_conn)
        if not existing:
            raise FileNotFoundError(f"Template '{template_id}' not found.")

        clean_name = name.strip() if name is not None else existing["name"]
        if not clean_name:
            raise ValueError("Template name must not be empty.")

        clean_content = content.strip() if content is not None else existing["content"]
        if not clean_content:
            raise ValueError("Template content must not be empty.")

        clean_order = display_order if display_order is not None else existing["display_order"]
        now = _now_iso()

        def _update():
            active_conn.execute(
                """
                UPDATE agent_prompt_templates
                SET name = ?, content = ?, display_order = ?, updated_at = ?
                WHERE template_id = ?
                """,
                (clean_name, clean_content, clean_order, now, template_id),
            )

        if is_generated:
            with active_conn:
                _update()
        else:
            _update()

        return get_prompt_template(template_id, conn=active_conn)  # type: ignore[return-value]


def delete_prompt_template(
    template_id: str, conn: Optional[sqlite3.Connection] = None
) -> bool:
    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                cursor = active_conn.execute(
                    "DELETE FROM agent_prompt_templates WHERE template_id = ?;",
                    (template_id,),
                )
                return cursor.rowcount > 0
        else:
            cursor = active_conn.execute(
                "DELETE FROM agent_prompt_templates WHERE template_id = ?;",
                (template_id,),
            )
            return cursor.rowcount > 0
