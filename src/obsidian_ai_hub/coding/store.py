"""SQLite store for coding sessions, messages, and runs."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from collections import Counter
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from obsidian_ai_hub.agents import registry
from obsidian_ai_hub.database import get_db_connection

JST = ZoneInfo("Asia/Tokyo")

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(JST).isoformat()


def _has_run_id_column(conn: sqlite3.Connection) -> bool:
    """Return True if coding_messages.run_id column exists (v30+).

    Centralizes PRAGMA introspection and handles sqlite3.Error explicitly
    instead of silently hiding DB errors. Used by both write and read paths
    to avoid duplicated schema checks.
    """
    try:
        cur = conn.execute("PRAGMA table_info(coding_messages)")
        cols = [r["name"] for r in cur.fetchall()]
        return "run_id" in cols
    except sqlite3.Error as exc:
        logger.warning("Failed to inspect coding_messages schema: %s", exc)
        return False


def mark_interrupted_runs_on_startup() -> int:
    """Mark any lingering 'running' runs and tool calls as 'interrupted' on startup."""
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
    conn.execute(
        """
        UPDATE coding_orchestrator_tool_calls
        SET status = 'interrupted',
            finished_at = ?,
            error = 'Interrupted due to server restart'
        WHERE status = 'running'
        """,
        (now,),
    )
    conn.commit()
    conn.close()
    return count


def mark_running_tool_calls_interrupted_for_run(
    run_id: str, error: str = "User cancelled execution"
) -> int:
    """Mark any running tool calls for a run as interrupted."""
    conn = get_db_connection()
    try:
        now = _now_iso()
        cursor = conn.execute(
            """
            UPDATE coding_orchestrator_tool_calls
            SET status = 'interrupted',
                finished_at = ?,
                error = ?
            WHERE run_id = ? AND status = 'running'
            """,
            (now, error, run_id),
        )
        count = cursor.rowcount
        conn.commit()
        return count
    finally:
        conn.close()


def create_orchestrator_tool_call(
    call_id: str,
    run_id: str,
    phase: str,
    phase_turn: int,
    iteration: int,
    call_index: int,
    call_key: str,
    tool_name: str,
    args: Dict[str, Any] | str,
    provider_call_id: Optional[str] = None,
    orchestrator_message_id: Optional[str] = None,
    status: str = "running",
) -> Dict[str, Any]:
    """Create a running orchestrator tool call record."""
    conn = get_db_connection()
    try:
        now = _now_iso()
        args_json = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)

        conn.execute(
            """
            INSERT INTO coding_orchestrator_tool_calls (
                call_id, run_id, phase, phase_turn, iteration, call_index, call_key,
                orchestrator_message_id, tool_name, args_json, status, provider_call_id, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call_id,
                run_id,
                phase,
                phase_turn,
                iteration,
                call_index,
                call_key,
                orchestrator_message_id,
                tool_name,
                args_json,
                status,
                provider_call_id,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_orchestrator_tool_call(call_id) or {}


def update_orchestrator_tool_call(
    call_id: str,
    status: str,
    result: Optional[str] = None,
    error: Optional[str] = None,
    orchestrator_message_id: Optional[str] = None,
    finished_at: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update orchestrator tool call status, result, error, or message linkage."""
    conn = get_db_connection()
    try:
        now = finished_at or _now_iso()
        updates = ["status = ?", "finished_at = ?"]
        params = [status, now]

        if result is not None:
            updates.append("result = ?")
            params.append(result)
        if error is not None:
            updates.append("error = ?")
            params.append(error)
        if orchestrator_message_id is not None:
            updates.append("orchestrator_message_id = ?")
            params.append(orchestrator_message_id)

        params.append(call_id)
        sql = f"UPDATE coding_orchestrator_tool_calls SET {', '.join(updates)} WHERE call_id = ?"
        conn.execute(sql, tuple(params))
        conn.commit()
    finally:
        conn.close()
    return get_orchestrator_tool_call(call_id)


def associate_orchestrator_tool_calls_with_message(
    run_id: str,
    phase_turn: int,
    orchestrator_message_id: str,
) -> int:
    """Link pending tool calls for (run_id, phase_turn) to the created orchestrator message."""
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE coding_orchestrator_tool_calls
            SET orchestrator_message_id = ?
            WHERE run_id = ? AND phase_turn = ? AND orchestrator_message_id IS NULL
            """,
            (orchestrator_message_id, run_id, phase_turn),
        )
        count = cursor.rowcount
        conn.commit()
        return count
    finally:
        conn.close()


def get_orchestrator_tool_call(
    call_id: str, conn=None
) -> Optional[Dict[str, Any]]:
    """Get orchestrator tool call record by call_id."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    cursor = conn.execute(
        "SELECT * FROM coding_orchestrator_tool_calls WHERE call_id = ?", (call_id,)
    )
    row = cursor.fetchone()
    if close_conn:
        conn.close()

    if not row:
        return None
    d = dict(row)
    if d.get("args_json"):
        try:
            d["args"] = json.loads(d["args_json"])
        except (json.JSONDecodeError, TypeError):
            d["args"] = {}
    else:
        d["args"] = {}
    return d


def list_orchestrator_tool_calls_for_run(
    run_id: str, conn=None
) -> List[Dict[str, Any]]:
    """List all orchestrator tool calls for a run."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    cursor = conn.execute(
        """
        SELECT * FROM coding_orchestrator_tool_calls
        WHERE run_id = ?
        ORDER BY phase_turn ASC, iteration ASC, call_index ASC
        """,
        (run_id,),
    )
    rows = cursor.fetchall()
    if close_conn:
        conn.close()

    res = []
    for r in rows:
        d = dict(r)
        if d.get("args_json"):
            try:
                d["args"] = json.loads(d["args_json"])
            except (json.JSONDecodeError, TypeError):
                d["args"] = {}
        else:
            d["args"] = {}
        res.append(d)
    return res


def list_orchestrator_tool_calls_for_session(
    session_id: str,
) -> List[Dict[str, Any]]:
    """List all orchestrator tool calls for a session across runs."""
    conn = get_db_connection()
    cursor = conn.execute(
        """
        SELECT tc.* FROM coding_orchestrator_tool_calls tc
        JOIN coding_runs r ON r.run_id = tc.run_id
        WHERE r.session_id = ?
        ORDER BY tc.phase_turn ASC, tc.iteration ASC, tc.call_index ASC
        """,
        (session_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    res = []
    for r in rows:
        d = dict(r)
        if d.get("args_json"):
            try:
                d["args"] = json.loads(d["args_json"])
            except (json.JSONDecodeError, TypeError):
                d["args"] = {}
        else:
            d["args"] = {}
        res.append(d)
    return res


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


def update_session_tool_ids(
    session_id: str, tool_ids: Optional[List[str]]
) -> Optional[List[str]]:
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
    cursor = conn.execute(
        "SELECT project_id FROM projects WHERE project_id = ?", (project_id,)
    )
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
        (
            session_id,
            project_id,
            backend,
            repo_path,
            external_session_id,
            title,
            tool_ids_json,
            now,
            now,
        ),
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


def _is_on_jst_date(value: str | None, target_date: date) -> bool:
    if not value:
        return False
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST).date() == target_date


def list_daily_session_overviews(target_date: date) -> List[Dict[str, Any]]:
    """Return metadata-only overviews for coding sessions started on a JST date."""
    conn = get_db_connection()
    try:
        session_rows = conn.execute(
            """
            SELECT coding_sessions.session_id, coding_sessions.project_id,
                   coding_sessions.backend, coding_sessions.title,
                   coding_sessions.created_at, projects.display_name AS project_name
            FROM coding_sessions
            INNER JOIN projects ON projects.project_id = coding_sessions.project_id
            ORDER BY coding_sessions.created_at ASC
            """
        ).fetchall()

        overviews = []
        for session in session_rows:
            if not _is_on_jst_date(session["created_at"], target_date):
                continue
            runs = conn.execute(
                """
                SELECT status, started_at FROM coding_runs
                WHERE session_id = ?
                """,
                (session["session_id"],),
            ).fetchall()
            status_counts = Counter(
                row["status"]
                for row in runs
                if _is_on_jst_date(row["started_at"], target_date)
            )
            overviews.append(
                {
                    "project_id": session["project_id"],
                    "project_name": session["project_name"],
                    "session_title": session["title"],
                    "backend": session["backend"],
                    "started_at": session["created_at"],
                    "run_count": sum(status_counts.values()),
                    "run_status_counts": dict(sorted(status_counts.items())),
                }
            )
        return overviews
    finally:
        conn.close()


def update_session_external_id(
    session_id: str, external_session_id: Optional[str]
) -> None:
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
    cursor = conn.execute(
        "DELETE FROM coding_sessions WHERE session_id = ?", (session_id,)
    )
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return count > 0


def update_message_run_id(message_id: str, run_id: str) -> None:
    """Link a message to a run_id."""
    conn = get_db_connection()
    if _has_run_id_column(conn):
        conn.execute(
            "UPDATE coding_messages SET run_id = ? WHERE message_id = ?",
            (run_id, message_id),
        )
        conn.commit()
    conn.close()


def add_message(
    session_id: str, role: str, content: str, run_id: Optional[str] = None
) -> Dict[str, Any]:
    """Add a message to a session.

    run_id is optional and, when provided (e.g., for worker messages), links the
    message to a specific coding run for post-hoc tracing. Column added in v30;
    ignored if migration not yet applied (fallback to without column).

    v30以降: coding_messages.run_id 列が正の関連（canonical）。junction への
    二重書き込みは不要のため行わない。migration前DBでは junction フォールバックで
    関連付けを維持する。
    """
    conn = get_db_connection()
    message_id = f"cmsg_{uuid.uuid4().hex[:12]}"
    now = _now_iso()

    cursor = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM coding_messages WHERE session_id = ?",
        (session_id,),
    )
    seq = cursor.fetchone()[0]

    # v30以降は run_id 列が唯一の正とする。列有無は helper で判定し重複 introspection を避ける。
    has_run_id_col = _has_run_id_column(conn)

    if has_run_id_col and run_id is not None:
        try:
            conn.execute(
                """
                INSERT INTO coding_messages (
                    message_id, session_id, sequence, role, content, created_at, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, seq, role, content, now, run_id),
            )
        except sqlite3.IntegrityError as exc:
            # Invalid run_id (FK violation) must not be silently hidden;
            # surface the inconsistency for caller handling.
            logger.error(
                "Integrity error inserting coding_messages %s with run_id %s: %s",
                message_id,
                run_id,
                exc,
            )
            conn.close()
            raise
        except sqlite3.Error as exc:
            logger.error(
                "DB error inserting coding_messages %s with run_id %s: %s",
                message_id,
                run_id,
                exc,
            )
            conn.close()
            raise
    else:
        conn.execute(
            """
            INSERT INTO coding_messages (
                message_id, session_id, sequence, role, content, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (message_id, session_id, seq, role, content, now),
        )
        # Fallback for legacy DB without column: still record linkage via junction table if provided
        # migration前は junction が唯一の追跡手段のため、失敗時は警告で継続せず例外を伝播して run を failed にできるようにする
        if run_id is not None:
            try:
                # Ensure junction table exists; create lazily if missing
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS coding_run_worker_messages (
                        run_id TEXT NOT NULL,
                        message_id TEXT NOT NULL,
                        seq INTEGER NOT NULL,
                        PRIMARY KEY (run_id, message_id),
                        FOREIGN KEY(run_id) REFERENCES coding_runs(run_id) ON DELETE CASCADE,
                        FOREIGN KEY(message_id) REFERENCES coding_messages(message_id) ON DELETE CASCADE
                    )
                    """
                )
                # Insert with seq auto
                cur2 = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM coding_run_worker_messages WHERE run_id = ?",
                    (run_id,),
                )
                jseq = cur2.fetchone()[0]
                conn.execute(
                    "INSERT OR IGNORE INTO coding_run_worker_messages (run_id, message_id, seq) VALUES (?, ?, ?)",
                    (run_id, message_id, jseq),
                )
            except sqlite3.Error as exc:
                logger.error(
                    "Failed to record junction linkage for message %s run %s: %s",
                    message_id,
                    run_id,
                    exc,
                )
                conn.close()
                raise
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


def append_run_worker_message(run_id: str, message_id: str) -> None:
    """Persist ordered linkage between run and worker message for P1-2 (idempotent).

    v30以降は coding_messages.run_id 列が唯一の正であり、junction への二重書き込みは
    不要のため行わない。migration前（列不存在）のみ junction で関連付けを行う。
    いずれの経路でも DB エラーは sqlite3.Error として明示的にログし、呼び出し元へ
    例外を伝播して run を failed に遷移させられるようにする。
    """
    conn = get_db_connection()
    try:
        has_run_id_col = _has_run_id_column(conn)
        # v30以降は add_message 側で run_id 列へ既に書き込み済みのため冗長呼び出しは不要
        if has_run_id_col:
            return

        # migration前互換: junction でのみ追跡
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS coding_run_worker_messages (
                run_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                PRIMARY KEY (run_id, message_id),
                FOREIGN KEY(run_id) REFERENCES coding_runs(run_id) ON DELETE CASCADE,
                FOREIGN KEY(message_id) REFERENCES coding_messages(message_id) ON DELETE CASCADE
            )
            """
        )
        cur = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM coding_run_worker_messages WHERE run_id = ?",
            (run_id,),
        )
        jseq = cur.fetchone()[0]
        try:
            conn.execute(
                "INSERT OR IGNORE INTO coding_run_worker_messages (run_id, message_id, seq) VALUES (?, ?, ?)",
                (run_id, message_id, jseq),
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.error(
                "Failed to append junction linkage run %s message %s (has_run_id_col=%s): %s",
                run_id,
                message_id,
                has_run_id_col,
                exc,
            )
            raise
    finally:
        conn.close()


def list_worker_messages_for_run(run_id: str) -> List[Dict[str, Any]]:
    """List all worker messages belonging to a run in creation order.

    v30以降は coding_messages.run_id 列を優先して取得し、行が存在すればそれを
    正とする。存在しない場合のみ junction テーブルへフォールバックする
    （migration前互換）。
    """
    conn = get_db_connection()
    try:
        # Prefer run_id column on coding_messages if available (helperで重複排除)
        if _has_run_id_column(conn):
            try:
                cur2 = conn.execute(
                    "SELECT * FROM coding_messages WHERE run_id = ? AND role = 'worker' ORDER BY sequence ASC",
                    (run_id,),
                )
                rows = cur2.fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except sqlite3.Error as exc:
                logger.warning(
                    "Failed to query coding_messages by run_id %s: %s", run_id, exc
                )
        # Fallback to junction table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS coding_run_worker_messages (
                run_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                PRIMARY KEY (run_id, message_id),
                FOREIGN KEY(run_id) REFERENCES coding_runs(run_id) ON DELETE CASCADE,
                FOREIGN KEY(message_id) REFERENCES coding_messages(message_id) ON DELETE CASCADE
            )
            """
        )
        cur = conn.execute(
            """
            SELECT cm.* FROM coding_messages cm
            JOIN coding_run_worker_messages j ON j.message_id = cm.message_id
            WHERE j.run_id = ? ORDER BY j.seq ASC
            """,
            (run_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _format_run(run_dict: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not run_dict:
        return None
    r = dict(run_dict)
    diag_str = r.get("diagnostics_json")
    if diag_str:
        try:
            r["diagnostics"] = json.loads(diag_str)
        except (json.JSONDecodeError, TypeError):
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
