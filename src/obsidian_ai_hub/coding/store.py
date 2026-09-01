"""SQLite store for coding sessions, messages, and runs."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from obsidian_ai_hub.agents import registry
from obsidian_ai_hub.database import get_db_connection

JST = ZoneInfo("Asia/Tokyo")


def _now_iso() -> str:
    return datetime.now(JST).isoformat()


def mark_interrupted_runs_on_startup() -> int:
    """Mark any lingering 'running' runs as 'interrupted' on startup."""
    conn = get_db_connection()
    now = _now_iso()
    cursor = conn.execute(
        """
        UPDATE coding_runs
        SET status = 'interrupted',
            finished_at = ?,
            error_message = 'Interrupted due to server restart'
        WHERE status = 'running'
        """,
        (now,),
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


def get_all_available_tool_ids() -> List[str]:
    """Return all registered tool IDs."""
    return [t["tool_id"] for t in registry.list_available_tools()]


def get_user_default_tool_ids(conn=None) -> List[str]:
    """Retrieve user default tool IDs from coding_settings.

    If setting is missing or invalid, falls back to all available tool IDs.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    cursor = conn.execute(
        "SELECT setting_value FROM coding_settings WHERE setting_key = 'default_tool_ids'"
    )
    row = cursor.fetchone()
    if close_conn:
        conn.close()

    if row and row["setting_value"]:
        try:
            val = json.loads(row["setting_value"])
            if isinstance(val, list):
                all_tools = set(get_all_available_tool_ids())
                return [t for t in val if isinstance(t, str) and t in all_tools]
        except (json.JSONDecodeError, TypeError):
            pass

    return get_all_available_tool_ids()


def update_user_default_tool_ids(tool_ids: List[str]) -> List[str]:
    """Validate and save user default tool IDs in coding_settings."""
    all_tools = set(get_all_available_tool_ids())
    clean_ids = [t for t in tool_ids if isinstance(t, str) and t in all_tools]

    conn = get_db_connection()
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO coding_settings (setting_key, setting_value, updated_at)
        VALUES ('default_tool_ids', ?, ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value = excluded.setting_value,
            updated_at = excluded.updated_at
        """,
        (json.dumps(clean_ids, ensure_ascii=False), now),
    )
    conn.commit()
    conn.close()
    return clean_ids


def get_session_tool_ids(session_id: str, conn=None) -> Optional[List[str]]:
    """Get explicitly configured tool_ids for a session, or None if unconfigured."""
    session = get_session(session_id, conn=conn)
    if not session or session.get("tool_ids_json") is None:
        return None

    try:
        val = json.loads(session["tool_ids_json"])
        if isinstance(val, list):
            all_tools = set(get_all_available_tool_ids())
            return [t for t in val if isinstance(t, str) and t in all_tools]
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def get_effective_session_tool_ids(session_id: str, conn=None) -> List[str]:
    """Get active tool_ids for a session (custom session setting if present, else user defaults)."""
    session_tools = get_session_tool_ids(session_id, conn=conn)
    if session_tools is not None:
        return session_tools
    return get_user_default_tool_ids(conn=conn)


def update_session_tool_ids(session_id: str, tool_ids: Optional[List[str]]) -> Optional[List[str]]:
    """Update custom tool_ids for a session. If tool_ids is None, resets to user default (sets tool_ids_json = NULL)."""
    conn = get_db_connection()
    now = _now_iso()

    if tool_ids is None:
        conn.execute(
            "UPDATE coding_sessions SET tool_ids_json = NULL, updated_at = ? WHERE session_id = ?",
            (now, session_id),
        )
        conn.commit()
        conn.close()
        return None

    all_tools = set(get_all_available_tool_ids())
    clean_ids = [t for t in tool_ids if isinstance(t, str) and t in all_tools]
    val_json = json.dumps(clean_ids, ensure_ascii=False)

    conn.execute(
        "UPDATE coding_sessions SET tool_ids_json = ?, updated_at = ? WHERE session_id = ?",
        (val_json, now, session_id),
    )
    conn.commit()
    conn.close()
    return clean_ids


def create_session(
    project_id: int,
    backend: str,
    repo_path: str,
    title: str = "新しいコーディングセッション",
    external_session_id: Optional[str] = None,
    tool_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new coding session."""
    conn = get_db_connection()
    # Verify project exists
    cursor = conn.execute("SELECT project_id FROM projects WHERE project_id = ?", (project_id,))
    if not cursor.fetchone():
        conn.close()
        raise ValueError(f"Project with id {project_id} does not exist")

    session_id = f"cses_{uuid.uuid4().hex[:12]}"
    now = _now_iso()

    if tool_ids is None:
        init_tool_ids = get_user_default_tool_ids(conn=conn)
        tool_ids_json = json.dumps(init_tool_ids, ensure_ascii=False)
    else:
        all_tools = set(get_all_available_tool_ids())
        clean_ids = [t for t in tool_ids if isinstance(t, str) and t in all_tools]
        tool_ids_json = json.dumps(clean_ids, ensure_ascii=False)

    conn.execute(
        """
        INSERT INTO coding_sessions (
            session_id, project_id, backend, repo_path, external_session_id, title, tool_ids_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, project_id, backend, repo_path, external_session_id, title, tool_ids_json, now, now),
    )
    conn.commit()

    session = get_session(session_id, conn=conn)
    conn.close()
    assert session is not None
    return session


def get_session(session_id: str, conn=None) -> Optional[Dict[str, Any]]:
    """Retrieve a coding session by ID."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    cursor = conn.execute(
        "SELECT * FROM coding_sessions WHERE session_id = ?", (session_id,)
    )
    row = cursor.fetchone()
    if close_conn:
        conn.close()

    if not row:
        return None
    return dict(row)


def list_sessions_by_project(project_id: int) -> List[Dict[str, Any]]:
    """List all coding sessions for a project."""
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT * FROM coding_sessions WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_session_external_id(session_id: str, external_session_id: Optional[str]) -> None:
    """Update external_session_id for a session."""
    conn = get_db_connection()
    now = _now_iso()
    conn.execute(
        "UPDATE coding_sessions SET external_session_id = ?, updated_at = ? WHERE session_id = ?",
        (external_session_id, now, session_id),
    )
    conn.commit()
    conn.close()


def update_session_title(session_id: str, title: str) -> None:
    """Update session title."""
    conn = get_db_connection()
    now = _now_iso()
    conn.execute(
        "UPDATE coding_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
        (title, now, session_id),
    )
    conn.commit()
    conn.close()


def delete_session(session_id: str) -> bool:
    """Delete a coding session."""
    conn = get_db_connection()
    cursor = conn.execute("DELETE FROM coding_sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return count > 0


def add_message(session_id: str, role: str, content: str) -> Dict[str, Any]:
    """Add a message to a session."""
    conn = get_db_connection()
    message_id = f"cmsg_{uuid.uuid4().hex[:12]}"
    now = _now_iso()

    cursor = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM coding_messages WHERE session_id = ?",
        (session_id,),
    )
    seq = cursor.fetchone()[0]

    conn.execute(
        """
        INSERT INTO coding_messages (
            message_id, session_id, sequence, role, content, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (message_id, session_id, seq, role, content, now),
    )
    conn.execute(
        "UPDATE coding_sessions SET updated_at = ? WHERE session_id = ?",
        (now, session_id),
    )
    conn.commit()

    cursor = conn.execute(
        "SELECT * FROM coding_messages WHERE message_id = ?", (message_id,)
    )
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    return dict(row)


def list_messages(session_id: str) -> List[Dict[str, Any]]:
    """List all messages for a session ordered by sequence."""
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT * FROM coding_messages WHERE session_id = ? ORDER BY sequence ASC",
        (session_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_message(message_id: str) -> Optional[Dict[str, Any]]:
    """Get a message by ID."""
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT * FROM coding_messages WHERE message_id = ?", (message_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def create_run(
    session_id: str, user_message_id: str, dirty_tree_at_start: Optional[str] = None
) -> Dict[str, Any]:
    """Create a coding run."""
    conn = get_db_connection()
    run_id = f"crun_{uuid.uuid4().hex[:12]}"
    now = _now_iso()

    conn.execute(
        """
        INSERT INTO coding_runs (
            run_id, session_id, user_message_id, status, dirty_tree_at_start, started_at
        ) VALUES (?, ?, ?, 'running', ?, ?)
        """,
        (run_id, session_id, user_message_id, dirty_tree_at_start, now),
    )
    conn.commit()

    run = get_run(run_id, conn=conn)
    conn.close()
    assert run is not None
    return run


def update_run(
    run_id: str,
    orchestrator_message_id: Optional[str] = None,
    worker_message_id: Optional[str] = None,
    status: Optional[str] = None,
    error_message: Optional[str] = None,
    finished_at: Optional[str] = None,
    diagnostics_json: Optional[str] = None,
) -> Dict[str, Any]:
    """Update run fields."""
    conn = get_db_connection()
    updates = []
    params = []

    if orchestrator_message_id is not None:
        updates.append("orchestrator_message_id = ?")
        params.append(orchestrator_message_id)
    if worker_message_id is not None:
        updates.append("worker_message_id = ?")
        params.append(worker_message_id)
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if error_message is not None:
        updates.append("error_message = ?")
        params.append(error_message)
    if finished_at is not None:
        updates.append("finished_at = ?")
        params.append(finished_at)
    if diagnostics_json is not None:
        updates.append("diagnostics_json = ?")
        params.append(diagnostics_json)

    if updates:
        sql = f"UPDATE coding_runs SET {', '.join(updates)} WHERE run_id = ?"
        params.append(run_id)
        conn.execute(sql, tuple(params))
        conn.commit()

    run = get_run(run_id, conn=conn)
    conn.close()
    assert run is not None
    return run


def _format_run(run_dict: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not run_dict:
        return None
    r = dict(run_dict)
    diag_str = r.get("diagnostics_json")
    if diag_str:
        try:
            r["diagnostics"] = json.loads(diag_str)
        except Exception:
            r["diagnostics"] = None
    else:
        r["diagnostics"] = None
    return r


def get_run(run_id: str, conn=None) -> Optional[Dict[str, Any]]:
    """Get run by ID."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    cursor = conn.execute("SELECT * FROM coding_runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    if close_conn:
        conn.close()

    if not row:
        return None
    return _format_run(dict(row))


def get_active_run_for_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get the currently running run for a session if any."""
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT * FROM coding_runs WHERE session_id = ? AND status = 'running' ORDER BY started_at DESC LIMIT 1",
        (session_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return _format_run(dict(row))


def get_latest_run_for_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get the latest run for a session."""
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT * FROM coding_runs WHERE session_id = ? ORDER BY started_at DESC LIMIT 1",
        (session_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return _format_run(dict(row))
