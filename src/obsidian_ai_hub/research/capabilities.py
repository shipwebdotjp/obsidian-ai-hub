"""Research theme proposal capabilities & search/read tools for Agents and Task Agent."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, timedelta
from typing import Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.research.db import auto_connection, get_current_timestamp

logger = logging.getLogger(__name__)


DAILY_EXCERPT_LIMIT = 500
WEEKLY_EXCERPT_LIMIT = 800
PERIODIC_NOTE_LIMIT = 3000


def _strip_front_matter(text: str) -> str:
    """Drop a leading YAML front-matter block. Unclosed blocks become empty."""
    if not text:
        return ""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return text.strip()
    lines = stripped.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :]).strip()
    return ""


def _is_placeholder_line(line: str) -> bool:
    """True for blank lines and Markdown scaffolding with no content.

    Empty Daily/Weekly templates are mostly headings and task checkboxes; the
    remaining text after stripping decoration decides whether the line carries
    decision material.
    """
    core = line.strip().lstrip("#>-* \t")
    core = core.replace("[ ]", "").replace("[x]", "").replace("[X]", "")
    core = core.strip(" *_`|")
    return core == ""


def _meaningful_excerpt(text: str, limit: int) -> str:
    """Front-matter-free, template-free excerpt of a note body."""
    body = _strip_front_matter(text)
    if not body:
        return ""
    lines = [
        line.rstrip()
        for line in body.splitlines()
        if not _is_placeholder_line(line)
    ]
    body = "\n".join(lines).strip()
    if not body:
        return ""
    if len(body) <= limit:
        return body
    return body[:limit] + "…"


def get_suggestion_request(
    request_key: str, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict]:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(
            "SELECT * FROM research_suggestion_requests WHERE request_key = ?",
            (request_key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)


def record_suggestion_request(
    request_key: str,
    theme_id: str,
    hitl_run_id: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    now = get_current_timestamp()
    rec = {
        "request_key": request_key,
        "theme_id": theme_id,
        "hitl_run_id": hitl_run_id,
        "created_at": now,
    }
    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                active_conn.execute(
                    "INSERT OR REPLACE INTO research_suggestion_requests (request_key, theme_id, hitl_run_id, created_at) VALUES (?, ?, ?, ?)",
                    (request_key, theme_id, hitl_run_id, now),
                )
        else:
            active_conn.execute(
                "INSERT OR REPLACE INTO research_suggestion_requests (request_key, theme_id, hitl_run_id, created_at) VALUES (?, ?, ?, ?)",
                (request_key, theme_id, hitl_run_id, now),
            )
    return rec


def propose_research_theme_handler(
    *,
    theme: str,
    direction: str = "",
    kind: str = "explore",
    why_now: str = "",
    confidence: float = 0.0,
    trusted_ctx: Optional[dict] = None,
) -> dict:
    theme = (theme or "").strip()
    if not theme:
        return {"error": "theme must not be blank"}
    if len(theme) > 80:
        return {"error": "theme must be 80 characters or fewer"}
    direction = (direction or "").strip()
    if len(direction) > 140:
        return {"error": "direction must be 140 characters or fewer"}
    if kind not in ("deep", "adjacent", "explore"):
        kind = "explore"

    # Build request_key for idempotency
    request_key = None
    if isinstance(trusted_ctx, dict):
        if trusted_ctx.get("task_id"):
            request_key = f"task:{trusted_ctx['task_id']}"
        elif trusted_ctx.get("run_id"):
            request_key = f"agent_run:{trusted_ctx['run_id']}"
        elif trusted_ctx.get("session_id"):
            request_key = f"agent_session:{trusted_ctx['session_id']}"

    if not request_key:
        from obsidian_ai_hub.research import db

        request_key = f"theme_key:{db.normalize_theme_key(theme)}"

    # Check idempotency table
    existing_req = get_suggestion_request(request_key)
    if existing_req:
        return {
            "status": "already_proposed",
            "theme_id": existing_req["theme_id"],
            "hitl_run_id": existing_req["hitl_run_id"],
            "message": f"この実行コンテキストですでに提案済みです (theme_id: {existing_req['theme_id']})",
        }

    # Perform candidate & HITL registration
    from obsidian_ai_hub.research.pipeline import create_theme_and_research

    result = create_theme_and_research(
        theme=theme,
        direction=direction,
        kind=kind,
        why_now=why_now,
        confidence=confidence,
        is_suggestion=True,
    )

    theme_id = result.get("theme_id", "")
    hitl_run_id = result.get("hitl_run_id", "") or ""

    if theme_id and hitl_run_id:
        try:
            record_suggestion_request(
                request_key=request_key,
                theme_id=theme_id,
                hitl_run_id=hitl_run_id,
            )
        except sqlite3.IntegrityError:
            existing = get_suggestion_request(request_key)
            if existing:
                return {
                    "status": "already_proposed",
                    "theme_id": existing["theme_id"],
                    "hitl_run_id": existing["hitl_run_id"],
                    "message": f"この実行コンテキストですでに提案済みです (theme_id: {existing['theme_id']})",
                }

    return result


def get_research_context_snapshot() -> dict:
    from obsidian_ai_hub.research import db
    from obsidian_ai_hub.utils import config, reader

    today = date.today()

    # Priority order matters: the runtime history gist keeps the head of this
    # JSON, so activities/themes/feedback (decision material) must precede the
    # daily/weekly note excerpts, which are the most likely to be empty or
    # template scaffolding.

    # 1. Recent 7 days activity
    activities = db.list_recent_activity_days(days=7)
    activities_summary = activities[:15]

    # 2. Existing research themes
    themes = db.list_themes()
    recent_themes = [
        {
            "theme_id": t["theme_id"],
            "theme": t["theme"],
            "status": t["status"],
            "kind": t.get("kind"),
        }
        for t in themes[:15]
    ]

    # 3. Feedback, rejected first (avoid repeating an idea the user refused)
    feedback_items = sorted(
        db.list_theme_feedback(limit=10),
        key=lambda item: 0 if item.get("feedback_decision") == "rejected" else 1,
    )

    # 4. Recent 7 days Daily Notes with meaningful excerpts only
    daily_notes = []
    for i in range(7):
        d = today - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        path = reader.get_daily_note_path(d)
        if not path.exists():
            continue
        excerpt = _meaningful_excerpt(
            reader.get_daily_note_content(d), DAILY_EXCERPT_LIMIT
        )
        if not excerpt:
            continue
        try:
            rel_path = str(path.relative_to(config.VAULT_PATH))
        except Exception:
            rel_path = str(path)
        daily_notes.append(
            {"date": d_str, "relative_path": rel_path, "content": excerpt}
        )

    # 5. Latest Weekly Note with a meaningful excerpt only
    weekly_path = reader.get_weekly_note_path(today)
    try:
        rel_weekly = str(weekly_path.relative_to(config.VAULT_PATH))
    except Exception:
        rel_weekly = str(weekly_path)
    weekly_excerpt = ""
    if weekly_path.exists():
        weekly_excerpt = _meaningful_excerpt(
            reader.get_weekly_note_content(today), WEEKLY_EXCERPT_LIMIT
        )
    latest_weekly = {"relative_path": rel_weekly, "content": weekly_excerpt}

    return {
        "recent_activities": activities_summary,
        "existing_themes": recent_themes,
        "recent_feedback": feedback_items,
        "daily_notes": daily_notes,
        "latest_weekly_note": latest_weekly,
    }


def search_research_theme_history(
    query: Optional[str] = None,
    status: Optional[str] = None,
    feedback_decision: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    from obsidian_ai_hub.research import db

    limit = max(1, min(limit, 20))
    themes = db.list_themes(status=status, q=query)
    if feedback_decision:
        themes = [t for t in themes if t.get("feedback_decision") == feedback_decision]

    out = []
    for t in themes[:limit]:
        out.append(
            {
                "theme_id": t["theme_id"],
                "theme": t["theme"],
                "direction": t.get("direction"),
                "kind": t.get("kind"),
                "why_now": t.get("why_now"),
                "status": t["status"],
                "feedback_decision": t.get("feedback_decision"),
                "feedback_reason": t.get("feedback_reason"),
                "feedback_comment": t.get("feedback_comment"),
                "latest_job": t.get("latest_job"),
                "created_at": t.get("created_at"),
            }
        )
    return out


def search_activities(
    query: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    project_id: Optional[int] = None,
    limit: int = 10,
) -> list[dict]:
    limit = max(1, min(limit, 20))

    where_clauses = []
    params: list = []

    if query:
        where_clauses.append("(summary LIKE ? OR keywords LIKE ?)")
        like_q = f"%{query}%"
        params.extend([like_q, like_q])

    if start_date:
        where_clauses.append("activity_date >= ?")
        params.append(start_date)

    if end_date:
        where_clauses.append("activity_date <= ?")
        params.append(end_date)

    if category:
        where_clauses.append("category = ?")
        params.append(category)

    if project_id is not None:
        where_clauses.append("project_id = ?")
        params.append(project_id)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT activity_id, activity_date, occurred_at, app_name, window_title,
                   summary, category, keywords, project_id
            FROM activity_logs
            {where_sql}
            ORDER BY activity_date DESC, occurred_at DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        for r in rows:
            if isinstance(r.get("keywords"), str):
                try:
                    r["keywords"] = json.loads(r["keywords"])
                except Exception:
                    pass
        return rows
    finally:
        conn.close()


def read_periodic_note(period_type: str, reference_date: str) -> dict:
    from datetime import date

    from obsidian_ai_hub.utils import config, reader

    try:
        ref_dt = date.fromisoformat(reference_date[:10])
    except Exception as exc:
        raise ValueError(
            f"Invalid reference_date format: {reference_date}. Expected YYYY-MM-DD"
        ) from exc

    if period_type == "day":
        content = reader.get_daily_note_content(ref_dt)
        path = reader.get_daily_note_path(ref_dt)
    elif period_type == "week":
        content = reader.get_weekly_note_content(ref_dt)
        path = reader.get_weekly_note_path(ref_dt)
    else:
        raise ValueError("period_type must be 'day' or 'week'")

    try:
        rel_path = str(path.relative_to(config.VAULT_PATH))
    except Exception:
        rel_path = str(path)

    # A missing note must not return the empty template as if it were content.
    if not path.exists():
        content = ""
        truncated = False
    else:
        content = _meaningful_excerpt(content, PERIODIC_NOTE_LIMIT)
        truncated = content.endswith("…")

    return {
        "period_type": period_type,
        "reference_date": reference_date,
        "relative_path": rel_path,
        "content": content,
        "truncated": truncated,
    }


def search_agent_conversations(
    query: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    query = (query or "").strip()
    if not query:
        raise ValueError("query must not be empty")

    limit = max(1, min(limit, 10))
    where_clauses = ["m.content LIKE ?"]
    params: list = [f"%{query}%"]

    if start_date:
        where_clauses.append("m.created_at >= ?")
        params.append(start_date)
    if end_date:
        clean_end = end_date.strip()
        if len(clean_end) == 10:
            try:
                next_day = (date.fromisoformat(clean_end) + timedelta(days=1)).isoformat()
                where_clauses.append("m.created_at < ?")
                params.append(next_day)
            except ValueError:
                where_clauses.append("m.created_at <= ?")
                params.append(clean_end)
        else:
            where_clauses.append("m.created_at <= ?")
            params.append(clean_end)
    if agent_id:
        where_clauses.append("s.agent_id = ?")
        params.append(agent_id)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT m.message_id, m.session_id, m.role, m.content, m.created_at,
                   s.agent_id, r.run_id
            FROM agent_messages m
            JOIN agent_sessions s ON m.session_id = s.session_id
            LEFT JOIN agent_runs r ON (r.user_message_id = m.message_id OR r.assistant_message_id = m.message_id)
            {where_sql}
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        rows = cursor.fetchall()
        results = []
        for r in rows:
            content = r["content"] or ""
            idx = content.casefold().find(query.casefold())
            if idx != -1:
                start = max(0, idx - 100)
                end = min(len(content), idx + len(query) + 100)
                excerpt = (
                    ("…" if start > 0 else "")
                    + content[start:end]
                    + ("…" if end < len(content) else "")
                )
            else:
                excerpt = content[:200] + ("…" if len(content) > 200 else "")

            results.append(
                {
                    "session_id": r["session_id"],
                    "run_id": r["run_id"],
                    "agent_id": r["agent_id"],
                    "message_id": r["message_id"],
                    "role": r["role"],
                    "excerpt": excerpt,
                    "created_at": r["created_at"],
                }
            )
        return results
    finally:
        conn.close()


def search_coding_history(
    query: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    project_id: Optional[int] = None,
    limit: int = 5,
) -> list[dict]:
    query = (query or "").strip()
    if not query:
        raise ValueError("query must not be empty")

    limit = max(1, min(limit, 10))
    where_clauses = ["m.content LIKE ?"]
    params: list = [f"%{query}%"]

    if start_date:
        where_clauses.append("m.created_at >= ?")
        params.append(start_date)
    if end_date:
        clean_end = end_date.strip()
        if len(clean_end) == 10:
            try:
                next_day = (date.fromisoformat(clean_end) + timedelta(days=1)).isoformat()
                where_clauses.append("m.created_at < ?")
                params.append(next_day)
            except ValueError:
                where_clauses.append("m.created_at <= ?")
                params.append(clean_end)
        else:
            where_clauses.append("m.created_at <= ?")
            params.append(clean_end)
    if project_id is not None:
        where_clauses.append("s.project_id = ?")
        params.append(project_id)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT m.message_id, m.session_id, m.role, m.content, m.created_at,
                   s.project_id, r.run_id
            FROM coding_messages m
            JOIN coding_sessions s ON m.session_id = s.session_id
            LEFT JOIN coding_runs r ON (r.user_message_id = m.message_id OR r.orchestrator_message_id = m.message_id OR r.worker_message_id = m.message_id)
            {where_sql}
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        rows = cursor.fetchall()
        results = []
        for r in rows:
            content = r["content"] or ""
            idx = content.casefold().find(query.casefold())
            if idx != -1:
                start = max(0, idx - 100)
                end = min(len(content), idx + len(query) + 100)
                excerpt = (
                    ("…" if start > 0 else "")
                    + content[start:end]
                    + ("…" if end < len(content) else "")
                )
            else:
                excerpt = content[:200] + ("…" if len(content) > 200 else "")

            results.append(
                {
                    "session_id": r["session_id"],
                    "run_id": r["run_id"],
                    "project_id": r["project_id"],
                    "message_id": r["message_id"],
                    "role": r["role"],
                    "excerpt": excerpt,
                    "created_at": r["created_at"],
                }
            )
        return results
    finally:
        conn.close()
