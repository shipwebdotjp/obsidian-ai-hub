"""AI Agent store for agents, sessions, messages, and runs (SQLite)."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Generator, Optional, Sequence
from zoneinfo import ZoneInfo

from obsidian_ai_hub.database import get_db_connection

logger = logging.getLogger(__name__)


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


def _validate_delegate_agent_ids(
    delegate_agent_ids: Sequence[str] | None,
    self_agent_id: Optional[str],
    conn: sqlite3.Connection,
) -> list[str]:
    if not delegate_agent_ids:
        return []

    valid: list[str] = []
    for target_id in delegate_agent_ids:
        if not isinstance(target_id, str):
            continue
        clean_id = target_id.strip()
        if not clean_id:
            continue
        if self_agent_id and clean_id == self_agent_id:
            raise ValueError("Agent cannot set itself as a delegate target.")
        if clean_id in valid:
            continue

        cursor = conn.execute("SELECT 1 FROM agents WHERE agent_id = ?;", (clean_id,))
        if not cursor.fetchone():
            raise ValueError(f"Delegate target agent '{clean_id}' does not exist.")
        valid.append(clean_id)

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
    delegate_agent_ids = []
    try:
        raw_del = row["delegate_agent_ids_json"]  # type: ignore[index]
        if raw_del:
            parsed_del = json.loads(raw_del)
            if isinstance(parsed_del, list):
                delegate_agent_ids = [str(x) for x in parsed_del if isinstance(x, str)]
    except (IndexError, KeyError, ValueError, json.JSONDecodeError, TypeError):
        delegate_agent_ids = []

    advanced_params = _advanced_params_from_row(row)
    try:
        pinned_at = row["pinned_at"]  # type: ignore[index]
    except (IndexError, KeyError, ValueError):
        pinned_at = None
    return {
        "agent_id": row["agent_id"],
        "name": row["name"],
        "system_prompt": row["system_prompt"],
        "provider": row["provider"],
        "model": row["model"],
        "tool_ids": tool_ids,
        "delegate_agent_ids": delegate_agent_ids,
        "advanced_params": advanced_params,
        "pinned_at": pinned_at,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_session(row: sqlite3.Row) -> dict[str, Any]:
    try:
        pinned_at = row["pinned_at"]  # type: ignore[index]
    except (IndexError, KeyError, ValueError):
        pinned_at = None
    try:
        title_is_edited = bool(row["title_is_edited"])  # type: ignore[index]
    except (IndexError, KeyError, ValueError):
        title_is_edited = False
    return {
        "session_id": row["session_id"],
        "agent_id": row["agent_id"],
        "title": row["title"],
        "title_is_edited": title_is_edited,
        "pinned_at": pinned_at,
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


AGENT_NON_TERMINAL_STATUSES = frozenset({"queued", "running", "cancelling", "waiting_user"})
AGENT_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
AGENT_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelling", "interrupted", "failed"}),
    "running": frozenset(
        {"succeeded", "failed", "cancelled", "cancelling", "waiting_user", "interrupted"}
    ),
    "cancelling": frozenset({"cancelled", "failed", "interrupted", "succeeded"}),
    "waiting_user": frozenset(
        {"running", "succeeded", "failed", "cancelled", "interrupted", "cancelling", "queued"}
    ),
}

AGENT_EVENT_TYPES = frozenset(
    {
        "thinking",
        "tool_call_detected",
        "tool_call_start",
        "tool_call_end",
        "text_append",
        "user_question",
        "done",
        "error",
        "cancelled",
    }
)


def _safe_row_get(row: sqlite3.Row, key: str) -> Any | None:
    try:
        return row[key]  # type: ignore[index]
    except (IndexError, KeyError, ValueError):
        return None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return any(r["name"] == column for r in cur.fetchall())
    except sqlite3.Error:
        return False


def is_agent_terminal(status: str) -> bool:
    return status in AGENT_TERMINAL_STATUSES


def is_agent_non_terminal(status: str) -> bool:
    return status in AGENT_NON_TERMINAL_STATUSES


def _validate_agent_transition(from_status: str, to_status: str) -> None:
    if from_status == to_status:
        return
    allowed = AGENT_ALLOWED_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise ValueError(
            f"Agent run transition '{from_status}' -> '{to_status}' is not allowed."
        )


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

    try:
        hitl_run_id = row["hitl_run_id"]  # type: ignore[index]
    except (IndexError, KeyError, ValueError):
        hitl_run_id = None

    slash_invocation = None
    try:
        raw_slash = row["slash_invocation_json"]  # type: ignore[index]
        if raw_slash:
            slash_invocation = json.loads(raw_slash)
    except (IndexError, KeyError, ValueError, json.JSONDecodeError, TypeError):
        slash_invocation = None

    return {
        "run_id": row["run_id"],
        "session_id": row["session_id"],
        "user_message_id": row["user_message_id"],
        "assistant_message_id": row["assistant_message_id"],
        "status": row["status"],
        "hitl_run_id": hitl_run_id,
        "slash_invocation": slash_invocation,
        "used_tools": used_tools,
        "created_hitl_run_ids": created_hitl_run_ids,
        "tool_calls": tool_calls,
        "error_message": row["error_message"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "idempotency_key": _safe_row_get(row, "idempotency_key"),
        "idempotency_hash": _safe_row_get(row, "idempotency_hash"),
        "created_instance_id": _safe_row_get(row, "created_instance_id"),
        "worker_instance_id": _safe_row_get(row, "worker_instance_id"),
    }


def create_agent(
    name: str,
    system_prompt: str,
    tool_ids: Sequence[str] | None = None,
    delegate_agent_ids: Sequence[str] | None = None,
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
        valid_delegate_ids = _validate_delegate_agent_ids(
            delegate_agent_ids, self_agent_id=agent_id, conn=active_conn
        )
        delegate_ids_json = json.dumps(valid_delegate_ids, ensure_ascii=False)

        def _do_insert():
            try:
                active_conn.execute(
                    """
                    INSERT INTO agents (agent_id, name, system_prompt, provider, model, tool_ids_json, advanced_params_json, delegate_agent_ids_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent_id,
                        clean_name,
                        clean_prompt,
                        clean_provider,
                        clean_model,
                        tool_ids_json,
                        advanced_params_json,
                        delegate_ids_json,
                        now,
                        now,
                    ),
                )
            except sqlite3.OperationalError as e:
                msg = str(e)
                if "delegate_agent_ids_json" in msg:
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
                    except sqlite3.OperationalError as e2:
                        if "advanced_params_json" in str(e2):
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
                elif "advanced_params_json" in msg:
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

        try:
            if is_generated:
                with active_conn:
                    _do_insert()
            else:
                _do_insert()
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise ValueError(f"Agent with name '{clean_name}' already exists.") from e
            raise

        return get_agent(agent_id, conn=active_conn)  # type: ignore[return-value]


def list_agents(conn: Optional[sqlite3.Connection] = None) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        try:
            cursor = active_conn.execute(
                "SELECT * FROM agents ORDER BY (pinned_at IS NOT NULL) DESC, pinned_at DESC, updated_at DESC;"
            )
        except sqlite3.OperationalError as e:
            if "no such column: pinned_at" in str(e):
                cursor = active_conn.execute("SELECT * FROM agents ORDER BY created_at DESC;")
            else:
                raise
        return [_row_to_agent(row) for row in cursor.fetchall()]


def get_agent(agent_id: str, conn: Optional[sqlite3.Connection] = None) -> dict[str, Any] | None:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute("SELECT * FROM agents WHERE agent_id = ?;", (agent_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_agent(row)


_PINNED_AT_UNSET: Any = object()


def update_agent(
    agent_id: str,
    name: Optional[str] = None,
    system_prompt: Optional[str] = None,
    tool_ids: Optional[Sequence[str]] = None,
    delegate_agent_ids: Optional[Sequence[str]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    advanced_params: Optional[dict[str, Any]] = None,
    pinned_at: Any = _PINNED_AT_UNSET,
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

        if delegate_agent_ids is not None:
            valid_delegate_ids = _validate_delegate_agent_ids(
                delegate_agent_ids, self_agent_id=agent_id, conn=active_conn
            )
        else:
            valid_delegate_ids = existing.get("delegate_agent_ids", [])
        delegate_ids_json = json.dumps(valid_delegate_ids, ensure_ascii=False)

        # advanced_params: None means keep existing; otherwise normalize and store
        if advanced_params is None:
            advanced_params_norm = existing.get("advanced_params", {})
        else:
            advanced_params_norm = _normalize_advanced_params(advanced_params)
        advanced_params_json = json.dumps(advanced_params_norm, ensure_ascii=False)
        if pinned_at is _PINNED_AT_UNSET:
            clean_pinned_at = existing.get("pinned_at")
        else:
            clean_pinned_at = pinned_at
        now = _now_iso()

        def _do_update():
            try:
                active_conn.execute(
                    """
                    UPDATE agents
                    SET name = ?, system_prompt = ?, provider = ?, model = ?, tool_ids_json = ?, advanced_params_json = ?, delegate_agent_ids_json = ?, pinned_at = ?, updated_at = ?
                    WHERE agent_id = ?
                    """,
                    (
                        clean_name,
                        clean_prompt,
                        clean_provider,
                        clean_model,
                        tool_ids_json,
                        advanced_params_json,
                        delegate_ids_json,
                        clean_pinned_at,
                        now,
                        agent_id,
                    ),
                )
            except sqlite3.OperationalError as e:
                msg = str(e)
                if "delegate_agent_ids_json" in msg:
                    try:
                        active_conn.execute(
                            """
                            UPDATE agents
                            SET name = ?, system_prompt = ?, provider = ?, model = ?, tool_ids_json = ?, advanced_params_json = ?, pinned_at = ?, updated_at = ?
                            WHERE agent_id = ?
                            """,
                            (
                                clean_name,
                                clean_prompt,
                                clean_provider,
                                clean_model,
                                tool_ids_json,
                                advanced_params_json,
                                clean_pinned_at,
                                now,
                                agent_id,
                            ),
                        )
                    except sqlite3.OperationalError as e2:
                        if "no such column: pinned_at" in str(e2):
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
                        else:
                            raise
                elif "no such column: pinned_at" in msg:
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
                    except sqlite3.OperationalError as e2:
                        if "no such column: advanced_params_json" in str(e2):
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
                elif "no such column: advanced_params_json" in msg:
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

        try:
            if is_generated:
                with active_conn:
                    _do_update()
            else:
                _do_update()
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise ValueError(f"Agent with name '{clean_name}' already exists.") from e
            raise

        return get_agent(agent_id, conn=active_conn)  # type: ignore[return-value]


def delete_agent(agent_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    with auto_connection(conn) as (active_conn, is_generated):
        def _execute_delete():
            cursor = active_conn.execute("DELETE FROM agents WHERE agent_id = ?;", (agent_id,))
            if cursor.rowcount == 0:
                return False

            # Remove agent_id from delegate_agent_ids_json of remaining agents
            try:
                rows = active_conn.execute(
                    "SELECT agent_id, delegate_agent_ids_json FROM agents;"
                ).fetchall()
                now = _now_iso()
                for row in rows:
                    raw = row["delegate_agent_ids_json"]
                    if not raw:
                        continue
                    try:
                        d_ids = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(d_ids, list) and agent_id in d_ids:
                        new_ids = [x for x in d_ids if x != agent_id]
                        new_json = json.dumps(new_ids, ensure_ascii=False)
                        active_conn.execute(
                            "UPDATE agents SET delegate_agent_ids_json = ?, updated_at = ? WHERE agent_id = ?;",
                            (new_json, now, row["agent_id"]),
                        )
            except sqlite3.OperationalError as e:
                if "no such column: delegate_agent_ids_json" not in str(e):
                    raise
            return True

        if is_generated:
            with active_conn:
                return _execute_delete()
        else:
            return _execute_delete()


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
        try:
            cursor = active_conn.execute(
                "SELECT * FROM agent_sessions WHERE agent_id = ? ORDER BY (pinned_at IS NOT NULL) DESC, pinned_at DESC, updated_at DESC;",
                (agent_id,),
            )
        except sqlite3.OperationalError as e:
            if "no such column: pinned_at" in str(e):
                cursor = active_conn.execute(
                    "SELECT * FROM agent_sessions WHERE agent_id = ? ORDER BY updated_at DESC;",
                    (agent_id,),
                )
            else:
                raise
        return [_row_to_session(row) for row in cursor.fetchall()]


def _is_on_jst_date(value: str | None, target_date: date) -> bool:
    if not value:
        return False
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo("Asia/Tokyo")).date() == target_date


def list_daily_session_overviews(target_date: date) -> list[dict[str, Any]]:
    """Return metadata-only overviews for agent sessions started on a JST date."""
    with auto_connection() as (conn, _):
        session_rows = conn.execute(
            """
            SELECT agent_sessions.session_id, agent_sessions.title,
                   agent_sessions.created_at, agents.name AS agent_name
            FROM agent_sessions
            INNER JOIN agents ON agents.agent_id = agent_sessions.agent_id
            ORDER BY agent_sessions.created_at ASC
            """
        ).fetchall()

        overviews = []
        for session in session_rows:
            if not _is_on_jst_date(session["created_at"], target_date):
                continue

            messages = conn.execute(
                """
                SELECT role, created_at FROM agent_messages
                WHERE session_id = ?
                """,
                (session["session_id"],),
            ).fetchall()
            runs = conn.execute(
                """
                SELECT status, started_at FROM agent_runs
                WHERE session_id = ?
                """,
                (session["session_id"],),
            ).fetchall()

            message_counts = Counter(
                row["role"]
                for row in messages
                if _is_on_jst_date(row["created_at"], target_date)
            )
            status_counts = Counter(
                row["status"]
                for row in runs
                if _is_on_jst_date(row["started_at"], target_date)
            )
            overviews.append(
                {
                    "agent_name": session["agent_name"],
                    "session_title": session["title"],
                    "started_at": session["created_at"],
                    "message_count": sum(message_counts.values()),
                    "user_message_count": message_counts["user"],
                    "assistant_message_count": message_counts["assistant"],
                    "run_status_counts": dict(sorted(status_counts.items())),
                }
            )
        return overviews


_SESSION_SEARCH_LIMIT = 100
_SESSION_SEARCH_SNIPPET_RADIUS = 72


def _escape_like_query(query: str) -> str:
    """Escape user input so LIKE remains a literal substring search."""
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _make_search_snippet(content: str, query: str) -> str:
    """Return a compact, whitespace-normalized excerpt around a matching term."""
    normalized = " ".join(content.split())
    if not normalized:
        return ""

    match_at = normalized.casefold().find(query.casefold())
    if match_at < 0:
        return normalized[: _SESSION_SEARCH_SNIPPET_RADIUS * 2].rstrip() + (
            "…" if len(normalized) > _SESSION_SEARCH_SNIPPET_RADIUS * 2 else ""
        )

    start = max(0, match_at - _SESSION_SEARCH_SNIPPET_RADIUS)
    end = min(len(normalized), match_at + len(query) + _SESSION_SEARCH_SNIPPET_RADIUS)
    prefix = "…" if start else ""
    suffix = "…" if end < len(normalized) else ""
    return f"{prefix}{normalized[start:end]}{suffix}"


def search_messages(
    query: str,
    conn: Optional[sqlite3.Connection] = None,
    limit: int = _SESSION_SEARCH_LIMIT,
) -> list[dict[str, Any]]:
    """Search persisted conversation messages across every agent.

    The current personal-use scale does not warrant an FTS table.  Keep the
    query literal (rather than treating '%' and '_' as wildcards) so the UI
    behaves like a normal substring search.
    """
    clean_query = (query or "").strip()
    if not clean_query:
        raise ValueError("Search query must not be empty.")

    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute(
            """
            SELECT
                agents.agent_id,
                agents.name AS agent_name,
                agent_sessions.session_id,
                agent_sessions.title AS session_title,
                agent_sessions.updated_at AS session_updated_at,
                agent_messages.message_id,
                agent_messages.role,
                agent_messages.content,
                agent_messages.created_at
            FROM agent_messages
            INNER JOIN agent_sessions
                ON agent_sessions.session_id = agent_messages.session_id
            INNER JOIN agents ON agents.agent_id = agent_sessions.agent_id
            WHERE agent_messages.content LIKE ? ESCAPE '\\'
            ORDER BY agent_sessions.updated_at DESC, agent_messages.sequence DESC
            LIMIT ?;
            """,
            (f"%{_escape_like_query(clean_query)}%", limit),
        )
        return [
            {
                "agent_id": row["agent_id"],
                "agent_name": row["agent_name"],
                "session_id": row["session_id"],
                "session_title": row["session_title"],
                "session_updated_at": row["session_updated_at"],
                "message_id": row["message_id"],
                "role": row["role"],
                "snippet": _make_search_snippet(row["content"], clean_query),
                "created_at": row["created_at"],
            }
            for row in cursor.fetchall()
        ]


def get_session(session_id: str, conn: Optional[sqlite3.Connection] = None) -> dict[str, Any] | None:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.execute(
            "SELECT * FROM agent_sessions WHERE session_id = ?;", (session_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_session(row)


def update_session_title(
    session_id: str,
    title: str,
    is_user_edit: bool = False,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Update session title.

    If is_user_edit is False (auto-generation), skip update if title_is_edited is True.
    If is_user_edit is True, update title and set title_is_edited = 1.
    """
    clean_title = title.strip() if title else ""
    if not clean_title:
        raise ValueError("Session title must not be empty.")

    with auto_connection(conn) as (active_conn, is_generated):
        existing = get_session(session_id, conn=active_conn)
        if not existing:
            raise FileNotFoundError(f"Session '{session_id}' not found.")

        # Only user-edited titles are protected here; auto-generation (is_user_edit=False)
        # relies on the caller (runtime) to fire only on the first turn.
        if not is_user_edit and existing.get("title_is_edited"):
            # Title was explicitly edited by user; do not overwrite
            return existing

        new_is_edited = 1 if is_user_edit else 0
        now = _now_iso()

        def _do_update():
            try:
                active_conn.execute(
                    "UPDATE agent_sessions SET title = ?, title_is_edited = ?, updated_at = ? WHERE session_id = ?;",
                    (clean_title, new_is_edited, now, session_id),
                )
            except sqlite3.OperationalError as e:
                if "no such column: title_is_edited" in str(e):
                    active_conn.execute(
                        "UPDATE agent_sessions SET title = ?, updated_at = ? WHERE session_id = ?;",
                        (clean_title, now, session_id),
                    )
                else:
                    raise

        if is_generated:
            with active_conn:
                _do_update()
        else:
            _do_update()

        return get_session(session_id, conn=active_conn)  # type: ignore[return-value]


def update_session(
    session_id: str,
    title: Optional[str] = None,
    pinned_at: Any = _PINNED_AT_UNSET,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    with auto_connection(conn) as (active_conn, is_generated):
        existing = get_session(session_id, conn=active_conn)
        if not existing:
            raise FileNotFoundError(f"Session '{session_id}' not found.")

        is_title_edited = title is not None
        clean_title = title.strip() if title is not None else existing["title"]
        if not clean_title:
            raise ValueError("Session title must not be empty.")

        title_is_edited_val = 1 if (is_title_edited or existing.get("title_is_edited")) else 0

        if pinned_at is _PINNED_AT_UNSET:
            clean_pinned_at = existing.get("pinned_at")
        else:
            clean_pinned_at = pinned_at

        now = _now_iso()

        def _do_update():
            sql_parts = ["title = ?", "title_is_edited = ?", "pinned_at = ?", "updated_at = ?"]
            params: list[Any] = [clean_title, title_is_edited_val, clean_pinned_at, now, session_id]
            optional_cols = {"title_is_edited": title_is_edited_val, "pinned_at": clean_pinned_at}

            while True:
                try:
                    active_conn.execute(
                        f"UPDATE agent_sessions SET {', '.join(sql_parts)} WHERE session_id = ?;",
                        tuple(params),
                    )
                    break
                except sqlite3.OperationalError as e:
                    msg = str(e)
                    dropped = False
                    for col in list(optional_cols.keys()):
                        if f"no such column: {col}" in msg:
                            val_to_remove = optional_cols[col]
                            sql_parts = [p for p in sql_parts if not p.startswith(f"{col} = ?")]
                            # Remove the matching parameter value from params
                            new_params = []
                            removed = False
                            for p in params:
                                if not removed and p is val_to_remove:
                                    removed = True
                                else:
                                    new_params.append(p)
                            params = new_params
                            del optional_cols[col]
                            dropped = True
                    if not dropped:
                        raise

        if is_generated:
            with active_conn:
                _do_update()
        else:
            _do_update()

        return get_session(session_id, conn=active_conn)  # type: ignore[return-value]


def get_active_run_for_session(
    session_id: str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any] | None:
    """Return the non-terminal run for a session, if any (newest first)."""
    with auto_connection(conn) as (active_conn, _):
        placeholders = ",".join("?" for _ in AGENT_NON_TERMINAL_STATUSES)
        cursor = active_conn.execute(
            f"SELECT * FROM agent_runs WHERE session_id = ? AND status IN ({placeholders}) "
            "ORDER BY started_at DESC LIMIT 1;",
            (session_id, *sorted(AGENT_NON_TERMINAL_STATUSES)),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_run(row)


def get_run_by_idempotency(
    session_id: str,
    idempotency_key: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any] | None:
    with auto_connection(conn) as (active_conn, _):
        if not _has_column(active_conn, "agent_runs", "idempotency_key"):
            return None
        cursor = active_conn.execute(
            "SELECT * FROM agent_runs WHERE session_id = ? AND idempotency_key = ?;",
            (session_id, idempotency_key),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_run(row)


def delete_session(session_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    with auto_connection(conn) as (active_conn, is_generated):
        active = get_active_run_for_session(session_id, conn=active_conn)
        if active is not None:
            raise ValueError(
                f"Session '{session_id}' has an active run "
                f"('{active['run_id']}' status={active['status']}); cancel it first."
            )

        def _do_delete() -> bool:
            cursor = active_conn.execute(
                "DELETE FROM agent_sessions WHERE session_id = ?;", (session_id,)
            )
            return cursor.rowcount > 0

        if is_generated:
            with active_conn:
                return _do_delete()
        else:
            return _do_delete()


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


def update_run_hitl(
    run_id: str,
    status: str,
    hitl_run_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Update run status and optional hitl_run_id link (e.g. for waiting_user or cancelled)."""
    with auto_connection(conn) as (active_conn, is_generated):
        run = get_run(run_id, conn=active_conn)
        if not run:
            raise FileNotFoundError(f"Run '{run_id}' not found.")

        def _do_update():
            try:
                active_conn.execute(
                    """
                    UPDATE agent_runs
                    SET status = ?, hitl_run_id = ?
                    WHERE run_id = ?
                    """,
                    (status, hitl_run_id, run_id),
                )
            except sqlite3.OperationalError as e:
                if "no such column: hitl_run_id" in str(e):
                    logger.warning(
                        "agent_runs.hitl_run_id missing; run %s status updated but HITL link dropped. Run migration v33.",
                        run_id,
                    )
                    active_conn.execute(
                        """
                        UPDATE agent_runs
                        SET status = ?
                        WHERE run_id = ?
                        """,
                        (status, run_id),
                    )
                else:
                    raise

        if is_generated:
            with active_conn:
                _do_update()
        else:
            _do_update()

        return get_run(run_id, conn=active_conn)  # type: ignore[return-value]


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


def compute_idempotency_hash(
    content: str,
    attachments_json: str = "[]",
    slash_invocation: Optional[dict[str, Any]] = None,
) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update((content or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((attachments_json or "[]").encode("utf-8"))
    if slash_invocation:
        h.update(b"\x00")
        canonical_slash = json.dumps(
            slash_invocation, sort_keys=True, ensure_ascii=False
        )
        h.update(canonical_slash.encode("utf-8"))
    return h.hexdigest()


def start_queued_run(
    session_id: str,
    content: str,
    attachments: Optional[Sequence[dict[str, Any]]] = None,
    idempotency_key: Optional[str] = None,
    idempotency_hash: Optional[str] = None,
    created_instance_id: Optional[str] = None,
    slash_invocation: Optional[dict[str, Any]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Queue a new agent run with idempotency and active-run guard.

    Same idempotency_key resend returns the first run without double save.
    Different body with same key raises ValueError containing 'conflict'.
    Active non-terminal run in the session raises ValueError containing 'active'.
    """
    clean_content = content.strip() if content else ""
    attachments_list: list[dict[str, Any]] = []
    if attachments:
        for item in attachments:
            if isinstance(item, dict):
                attachments_list.append(item)
    try:
        attachments_json = json.dumps(attachments_list, ensure_ascii=False)
    except (TypeError, ValueError):
        attachments_json = "[]"
        attachments_list = []
    if not clean_content and not attachments_list:
        raise ValueError("Message content must not be empty.")
    clean_key = (idempotency_key or "").strip() or None
    if clean_key is not None and idempotency_hash is None:
        idempotency_hash = compute_idempotency_hash(clean_content, attachments_json, slash_invocation)
    elif clean_key is None:
        idempotency_hash = None

    slash_invocation_json = (
        json.dumps(slash_invocation, ensure_ascii=False)
        if slash_invocation
        else None
    )

    with auto_connection(conn) as (active_conn, is_generated):
        session = get_session(session_id, conn=active_conn)
        if not session:
            raise FileNotFoundError(f"Session '{session_id}' not found.")

        has_idem_cols = _has_column(active_conn, "agent_runs", "idempotency_key")
        has_slash_col = _has_column(active_conn, "agent_runs", "slash_invocation_json")

        def _execute() -> tuple[str, str]:
            # Idempotent replay first: same key returns first run.
            if clean_key is not None and has_idem_cols:
                cur = active_conn.execute(
                    "SELECT * FROM agent_runs WHERE session_id = ? AND idempotency_key = ?;",
                    (session_id, clean_key),
                )
                existing_row = cur.fetchone()
                if existing_row is not None:
                    existing = _row_to_run(existing_row)
                    if (existing.get("idempotency_hash") or None) != (
                        idempotency_hash or None
                    ):
                        raise ValueError(
                            f"Idempotency key conflict for session '{session_id}'."
                        )
                    return str(existing["user_message_id"]), str(existing["run_id"])

            # Active-run guard.
            placeholders = ",".join("?" for _ in AGENT_NON_TERMINAL_STATUSES)
            cur = active_conn.execute(
                f"SELECT run_id FROM agent_runs WHERE session_id = ? AND status IN ({placeholders}) LIMIT 1;",
                (session_id, *sorted(AGENT_NON_TERMINAL_STATUSES)),
            )
            if cur.fetchone() is not None:
                raise ValueError(
                    f"Session '{session_id}' already has an active run; cancel it first."
                )

            now = _now_iso()
            cur = active_conn.execute(
                "SELECT MAX(sequence) FROM agent_messages WHERE session_id = ?;",
                (session_id,),
            )
            max_seq_row = cur.fetchone()
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
            if has_idem_cols and has_slash_col:
                active_conn.execute(
                    """
                    INSERT INTO agent_runs (
                        run_id, session_id, user_message_id, assistant_message_id, status,
                        used_tools_json, created_hitl_run_ids_json, error_message, started_at, finished_at,
                        idempotency_key, idempotency_hash, created_instance_id, worker_instance_id,
                        slash_invocation_json
                    )
                    VALUES (?, ?, ?, NULL, 'queued', '[]', '[]', NULL, ?, NULL, ?, ?, ?, NULL, ?)
                    """,
                    (
                        run_id,
                        session_id,
                        message_id,
                        now,
                        clean_key,
                        idempotency_hash,
                        created_instance_id,
                        slash_invocation_json,
                    ),
                )
            elif has_idem_cols:
                if slash_invocation is not None:
                    raise ValueError("slash_invocation requires slash_invocation_json column (run migration v37).")
                active_conn.execute(
                    """
                    INSERT INTO agent_runs (
                        run_id, session_id, user_message_id, assistant_message_id, status,
                        used_tools_json, created_hitl_run_ids_json, error_message, started_at, finished_at,
                        idempotency_key, idempotency_hash, created_instance_id, worker_instance_id
                    )
                    VALUES (?, ?, ?, NULL, 'queued', '[]', '[]', NULL, ?, NULL, ?, ?, ?, NULL)
                    """,
                    (
                        run_id,
                        session_id,
                        message_id,
                        now,
                        clean_key,
                        idempotency_hash,
                        created_instance_id,
                    ),
                )
            else:
                if slash_invocation is not None:
                    raise ValueError("slash_invocation requires slash_invocation_json column (run migration v37).")
                active_conn.execute(
                    """
                    INSERT INTO agent_runs (
                        run_id, session_id, user_message_id, assistant_message_id, status,
                        used_tools_json, created_hitl_run_ids_json, error_message, started_at, finished_at
                    )
                    VALUES (?, ?, ?, NULL, 'queued', '[]', '[]', NULL, ?, NULL)
                    """,
                    (run_id, session_id, message_id, now),
                )
            if session["title"] == "新しい会話" and next_seq == 1:
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

        try:
            if is_generated:
                with active_conn:
                    msg_id, r_id = _execute()
            else:
                msg_id, r_id = _execute()
        except sqlite3.IntegrityError as e:
            msg_text = str(e)
            # Idempotency race: same key inserted concurrently.
            if clean_key is not None and "UNIQUE" in msg_text and "single_active" not in msg_text:
                existing = get_run_by_idempotency(session_id, clean_key, conn=active_conn)
                if existing is not None:
                    if (existing.get("idempotency_hash") or None) != (
                        idempotency_hash or None
                    ):
                        raise ValueError(
                            f"Idempotency key conflict for session '{session_id}'."
                        ) from e
                    msg = get_message(existing["user_message_id"], conn=active_conn)
                    return msg, existing  # type: ignore[return-value]
            # Single-active partial index race: concurrent start won.
            if "UNIQUE" in msg_text and "single_active" in msg_text:
                raise ValueError(
                    f"Session '{session_id}' already has an active run; cancel it first."
                ) from e
            raise

        msg = get_message(msg_id, conn=active_conn)
        run = get_run(r_id, conn=active_conn)
        return msg, run  # type: ignore[return-value]


def claim_queued_run(
    worker_instance_id: str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any] | None:
    """Claim the oldest queued run for this worker (queued -> running)."""
    with auto_connection(conn) as (active_conn, is_generated):
        def _execute() -> dict[str, Any] | None:
            cur = active_conn.execute(
                "SELECT * FROM agent_runs WHERE status = 'queued' ORDER BY started_at ASC LIMIT 1;"
            )
            row = cur.fetchone()
            if row is None:
                return None
            run_id = row["run_id"]
            has_worker_col = _has_column(active_conn, "agent_runs", "worker_instance_id")
            if has_worker_col:
                cur2 = active_conn.execute(
                    "UPDATE agent_runs SET status = 'running', worker_instance_id = ? "
                    "WHERE run_id = ? AND status = 'queued';",
                    (worker_instance_id, run_id),
                )
            else:
                cur2 = active_conn.execute(
                    "UPDATE agent_runs SET status = 'running' WHERE run_id = ? AND status = 'queued';",
                    (run_id,),
                )
            if cur2.rowcount == 0:
                return None
            return get_run(run_id, conn=active_conn)

        if is_generated:
            with active_conn:
                return _execute()
        else:
            return _execute()


def transition_run_status(
    run_id: str,
    to_status: str,
    error_message: Optional[str] = None,
    finished: bool = False,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    with auto_connection(conn) as (active_conn, is_generated):
        run = get_run(run_id, conn=active_conn)
        if not run:
            raise FileNotFoundError(f"Run '{run_id}' not found.")
        from_status = str(run["status"])
        _validate_agent_transition(from_status, to_status)
        if from_status == to_status:
            return run
        now = _now_iso()

        def _do() -> None:
            if finished:
                cur = active_conn.execute(
                    "UPDATE agent_runs SET status = ?, error_message = COALESCE(?, error_message), finished_at = ? "
                    "WHERE run_id = ? AND status = ?;",
                    (to_status, error_message, now, run_id, from_status),
                )
            elif error_message is not None:
                cur = active_conn.execute(
                    "UPDATE agent_runs SET status = ?, error_message = ? WHERE run_id = ? AND status = ?;",
                    (to_status, error_message, run_id, from_status),
                )
            else:
                cur = active_conn.execute(
                    "UPDATE agent_runs SET status = ? WHERE run_id = ? AND status = ?;",
                    (to_status, run_id, from_status),
                )
            if cur.rowcount == 0:
                current = get_run(run_id, conn=active_conn)
                raise ValueError(
                    f"Agent run '{run_id}' changed concurrently "
                    f"(expected '{from_status}', now '{(current or {}).get('status')}')."
                )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
        return get_run(run_id, conn=active_conn)  # type: ignore[return-value]


def request_cancel_run(
    run_id: str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any]:
    with auto_connection(conn) as (active_conn, is_generated):
        run = get_run(run_id, conn=active_conn)
        if not run:
            raise FileNotFoundError(f"Run '{run_id}' not found.")
        status = str(run["status"])
        if status in AGENT_TERMINAL_STATUSES:
            return run
        if status == "cancelling":
            return run
        _validate_agent_transition(status, "cancelling")

        def _do() -> None:
            active_conn.execute(
                "UPDATE agent_runs SET status = 'cancelling' WHERE run_id = ?;",
                (run_id,),
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()
        return get_run(run_id, conn=active_conn)  # type: ignore[return-value]


def mark_runs_interrupted(
    only_mine: bool = False,
    owner_instance_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Mark non-terminal runs as interrupted.

    Shutdown recovery: with only_mine=True interrupts only runs owned by
    owner_instance_id. Without owner filter interrupts all non-terminal runs.
    Returns affected row count.
    """
    with auto_connection(conn) as (active_conn, is_generated):
        now = _now_iso()
        placeholders = ",".join("?" for _ in AGENT_NON_TERMINAL_STATUSES)
        params: list[Any] = list(sorted(AGENT_NON_TERMINAL_STATUSES))

        sql = (
            f"UPDATE agent_runs SET status = 'interrupted', "
            f"error_message = COALESCE(error_message, 'Interrupted'), finished_at = COALESCE(finished_at, ?) "
            f"WHERE status IN ({placeholders})"
        )
        full_params: list[Any] = [now, *params]
        if only_mine and owner_instance_id is not None:
            has_worker = _has_column(active_conn, "agent_runs", "worker_instance_id")
            has_created = _has_column(active_conn, "agent_runs", "created_instance_id")
            if has_worker and has_created:
                sql += " AND (worker_instance_id = ? OR (worker_instance_id IS NULL AND created_instance_id = ?))"
                full_params.extend([owner_instance_id, owner_instance_id])
            elif has_created:
                sql += " AND created_instance_id = ?"
                full_params.append(owner_instance_id)

        def _do() -> int:
            cur = active_conn.execute(sql, tuple(full_params))
            # Also interrupt events? Events are immutable log; terminal event
            # is appended by caller transactionally when possible.
            return cur.rowcount

        if is_generated:
            with active_conn:
                count = _do()
        else:
            count = _do()
        return count


def mark_other_instances_interrupted(
    current_instance_id: str, conn: Optional[sqlite3.Connection] = None
) -> int:
    """Startup recovery: interrupt non-terminal runs not owned by current instance.

    NULL-safe: COALESCE treats missing ownership as not-owned, so orphaned
    queued runs from a dead process are also interrupted.
    """
    with auto_connection(conn) as (active_conn, is_generated):
        now = _now_iso()
        has_worker = _has_column(active_conn, "agent_runs", "worker_instance_id")
        has_created = _has_column(active_conn, "agent_runs", "created_instance_id")
        placeholders = ",".join("?" for _ in AGENT_NON_TERMINAL_STATUSES)
        base_params = list(sorted(AGENT_NON_TERMINAL_STATUSES))
        if has_worker and has_created:
            sql = (
                f"UPDATE agent_runs SET status = 'interrupted', "
                "error_message = COALESCE(error_message, 'Interrupted due to server restart'), "
                "finished_at = COALESCE(finished_at, ?) "
                f"WHERE status IN ({placeholders}) AND NOT "
                "(COALESCE(worker_instance_id, '') = ? OR COALESCE(created_instance_id, '') = ?)"
            )
            params = [now, *base_params, current_instance_id, current_instance_id]
        else:
            sql = (
                f"UPDATE agent_runs SET status = 'interrupted', "
                "error_message = COALESCE(error_message, 'Interrupted due to server restart'), "
                "finished_at = COALESCE(finished_at, ?) "
                f"WHERE status IN ({placeholders})"
            )
            params = [now, *base_params]

        def _do() -> int:
            cur = active_conn.execute(sql, tuple(params))
            return cur.rowcount

        if is_generated:
            with active_conn:
                return _do()
        else:
            return _do()


def append_run_event(
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    if event_type not in AGENT_EVENT_TYPES:
        raise ValueError(f"Unknown agent event type: '{event_type}'")
    # Ensure parent run exists before appending (FK safety + clearer error).
    with auto_connection(conn) as (active_conn, is_generated):
        if get_run(run_id, conn=active_conn) is None:
            raise FileNotFoundError(f"Run '{run_id}' not found.")
        now = _now_iso()
        payload_json = json.dumps(payload, ensure_ascii=False)

        def _do() -> int:
            cur = active_conn.execute(
                "INSERT INTO agent_run_events (run_id, event_type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?);",
                (run_id, event_type, payload_json, now),
            )
            return int(cur.lastrowid or 0)

        if is_generated:
            with active_conn:
                return _do()
        else:
            return _do()


def list_run_events(
    run_id: str,
    after_id: int = 0,
    limit: int = 500,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict[str, Any]]:
    with auto_connection(conn) as (active_conn, _):
        try:
            cursor = active_conn.execute(
                "SELECT event_id, run_id, event_type, payload_json, created_at "
                "FROM agent_run_events WHERE run_id = ? AND event_id > ? "
                "ORDER BY event_id ASC LIMIT ?;",
                (run_id, after_id, limit),
            )
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return []
            raise
        out: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            try:
                payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
            except (json.JSONDecodeError, TypeError):
                payload = {}
            out.append(
                {
                    "event_id": row["event_id"],
                    "run_id": row["run_id"],
                    "event_type": row["event_type"],
                    "payload": payload,
                    "created_at": row["created_at"],
                }
            )
        return out


def purge_old_run_events(retention_days: int = 7, conn: Optional[sqlite3.Connection] = None) -> int:
    """Delete event rows for terminal runs finished more than retention_days ago."""
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    with auto_connection(conn) as (active_conn, is_generated):
        placeholders = ",".join("?" for _ in AGENT_TERMINAL_STATUSES)

        def _do() -> int:
            try:
                cur = active_conn.execute(
                    f"DELETE FROM agent_run_events WHERE run_id IN ("
                    f"SELECT run_id FROM agent_runs WHERE status IN ({placeholders}) "
                    f"AND finished_at IS NOT NULL AND finished_at < ?);",
                    (*sorted(AGENT_TERMINAL_STATUSES), cutoff),
                )
                return cur.rowcount
            except sqlite3.OperationalError as e:
                if "no such table" in str(e):
                    return 0
                raise

        if is_generated:
            with active_conn:
                return _do()
        else:
            return _do()


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
