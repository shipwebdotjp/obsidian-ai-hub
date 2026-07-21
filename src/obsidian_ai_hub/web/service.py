import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from obsidian_ai_hub import memory
from obsidian_ai_hub.activity import store as activity_store
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.handler import obsidian_vault_retriever
from obsidian_ai_hub.people_sync.sync import (
    get_db_vault_conflicts_report,
    merge_display_orders,
)
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.utils.people_loader import load_people_notes_with_report
from obsidian_ai_hub.web import schemas

import calendar

logger = logging.getLogger(__name__)


def list_memories(
    status: Optional[str] = None,
    kind: Optional[str] = None,
    topic: Optional[str] = None,
    q: Optional[str] = None,
) -> list[dict]:
    rows = memory.load_all_memories()
    out = []
    for r in rows:
        if status and r.get("status") != status:
            continue
        if kind and r.get("kind") != kind:
            continue
        if topic and topic not in (r.get("topics") or []):
            continue
        if q:
            target = (r.get("content") or "") + " " + " ".join(r.get("tags") or [])
            if q.lower() not in target.lower():
                continue
        out.append(r)
    return out


def get_memory(memory_id: str) -> Optional[dict]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return memory.deserialize_memory(dict(row))
    finally:
        conn.close()


def get_events(memory_id: str) -> list[dict]:
    return memory.get_memory_events(memory_id)


REVIEW_ACTIONS = {"approve", "reject", "edit"}


def review_memory(
    memory_id: str, action: str, new_content: Optional[str] = None
) -> dict:
    if action not in REVIEW_ACTIONS:
        raise ValueError("action must be approve/reject/edit")
    if action == "edit" and not (new_content and new_content.strip()):
        raise ValueError("new_content is required for edit action")

    if action == "edit":
        payload = {"content": new_content}
        result = memory.update_memory_fields(memory_id, payload)
        if not result["found"]:
            raise LookupError(memory_id)
        return result["memory"]
    ok = memory.review_memory(memory_id, action, new_content)
    if not ok:
        raise LookupError(memory_id)
    return get_memory(memory_id)


def update_memory(memory_id: str, fields: dict) -> dict:
    return memory.update_memory_fields(memory_id, fields)


def batch_review(memory_ids: list, action: str) -> dict:
    if action not in schemas.ALLOWED_ACTIONS:
        raise ValueError("action must be approve/reject")
    return memory.batch_review_memories(memory_ids, action)


def resolve_memory(
    candidate_id: str,
    action: str,
    target_memory_id: str,
    integrated_content: Optional[str] = None,
    switch_date: Optional[str] = None,
) -> tuple[dict, Optional[dict]]:
    return memory.resolve_memory(
        candidate_id,
        action,
        target_memory_id,
        integrated_content=integrated_content,
        switch_date=switch_date,
    )


def delete_memory(memory_id: str) -> dict:
    return memory.delete_memory(memory_id)


def batch_delete(memory_ids: list[str]) -> dict:
    return memory.batch_delete_memories(memory_ids)


def get_memory_options() -> dict:
    from obsidian_ai_hub.utils.topics import TOPIC_ENUM

    kinds_order = [
        "preference",
        "decision_policy",
        "fact",
        "commitment",
        "pattern",
        "episode",
    ]
    kinds = [k for k in kinds_order if k in schemas.ALLOWED_KINDS]
    for k in sorted(list(schemas.ALLOWED_KINDS)):
        if k not in kinds_order:
            kinds.append(k)
    return {"kinds": kinds, "topics": list(TOPIC_ENUM)}


def render_copilot_profile() -> list[str]:
    return memory.render_copilot_profile()


# --- Research Theme services ---


def list_research_themes(
    status: Optional[str] = None,
    job_status: Optional[str] = None,
    q: Optional[str] = None,
) -> list[dict]:
    from obsidian_ai_hub.research import db

    return db.list_themes(status=status, job_status=job_status, q=q)


def get_research_theme(theme_id: str) -> Optional[dict]:
    from obsidian_ai_hub.research import db

    theme = db.get_theme(theme_id)
    if theme is None:
        return None
    job = db.latest_job(theme_id)
    theme["latest_job"] = job
    return theme


def review_research_theme(
    theme_id: str, action: str, reason: Optional[str] = None
) -> Optional[dict]:
    from obsidian_ai_hub.research import db
    from obsidian_ai_hub import research_agent

    theme = db.get_theme(theme_id)
    if theme is None:
        return None
    if action == "approve":
        job = db.latest_job(theme_id)
        if job and job.get("status") == "succeeded" and job.get("markdown"):
            research_agent.save_research_to_vault(theme_id)
        db.set_status(theme_id, "approved", reviewed_by="user", reason=reason)
    elif action == "reject":
        db.set_status(theme_id, "rejected", reviewed_by="user", reason=reason)
    else:
        raise ValueError(f"Invalid action: {action}")
    return db.get_theme(theme_id)


def rerun_research_theme(theme_id: str) -> Optional[dict]:
    from obsidian_ai_hub import research_agent

    job = research_agent.run_theme_research(theme_id)
    return job


def run_research_theme(theme: str, mode: str = "auto") -> tuple[dict, dict]:
    from obsidian_ai_hub.research.runner import (
        get_or_create_theme_and_job,
        submit_research_job_bg,
    )
    from obsidian_ai_hub.research import db

    theme_rec, job_rec = get_or_create_theme_and_job(theme=theme, mode=mode)
    try:
        submit_research_job_bg(
            theme_id=theme_rec["theme_id"],
            job_id=job_rec["job_id"],
            mode=mode,
        )
    except Exception as e:
        logger.exception("Failed to submit background research job")
        db.update_job(job_rec["job_id"], status="failed", error=str(e))
        raise
    return theme_rec, job_rec


# --- Vault Search services ---

_vault_search_lock = threading.Lock()


def search_vault(q: str, k: int = 10, mode: str = "hybrid") -> dict:
    with _vault_search_lock:
        result_json = obsidian_vault_retriever.search_obsidian_vault.func(
            query=q, k=k, search_mode=mode
        )
    try:
        results = json.loads(result_json)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse vault search JSON output: %s", e)
        raise ValueError("vault search returned invalid JSON") from e
    if isinstance(results, dict) and "error" in results:
        raise ValueError(results["error"])
    from obsidian_ai_hub.utils import config

    vault_name = Path(config.VAULT_PATH).name
    for hit in results:
        if not isinstance(hit.get("metadata"), dict):
            hit["metadata"] = {}
        hit["metadata"]["vault_name"] = vault_name
    return {"items": results, "total": len(results)}


def get_vault_file(relative_path: str) -> dict:
    from obsidian_ai_hub.utils import config

    vault_dir = Path(config.VAULT_PATH).resolve()

    p = Path(relative_path)
    if p.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    if ".." in p.parts:
        raise ValueError("Path traversal components (..) are not allowed")

    if p.suffix.lower() != ".md":
        raise ValueError("Only Markdown (.md) files are allowed")

    # Resolve resolved path (to handle symlinks properly)
    try:
        resolved_path = (vault_dir / p).resolve(strict=True)
    except FileNotFoundError:
        # Check traversal on non-existing path
        resolved_path = (vault_dir / p).resolve(strict=False)
        try:
            resolved_path.relative_to(vault_dir)
        except ValueError:
            raise ValueError("Path is outside the Vault")
        raise FileNotFoundError("File not found")

    # Verify containment for existing file
    try:
        resolved_path.relative_to(vault_dir)
    except ValueError:
        raise ValueError("Path is outside the Vault")

    if not resolved_path.is_file():
        raise FileNotFoundError("File is not a file")

    with open(resolved_path, "r", encoding="utf-8") as f:
        content = f.read()

    return {
        "content": content,
        "relative_path": relative_path,
    }


# --- Dashboard services ---


def parse_iso_datetime(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def get_day_activity_times(
    activity_logs: list[dict[str, Any]],
    target_date_str: str,
    now: Optional[datetime] = None,
) -> tuple[float, float]:
    """
    Returns (active_minutes, inactive_minutes).
    """
    if now is None:
        now = datetime.now()

    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except ValueError:
        return 0.0, 1440.0

    if target_date > now.date():
        return 0.0, 0.0

    is_today = target_date == now.date()
    day_start = datetime.combine(target_date, datetime.min.time())

    if is_today:
        day_end = now
        total_seconds = max(0.0, (now - day_start).total_seconds())
    else:
        day_end = datetime.combine(target_date, datetime.max.time())
        total_seconds = 24 * 3600.0

    intervals = []
    for log in activity_logs:
        occurred_at_str = log.get("occurred_at")
        if not occurred_at_str:
            continue
        try:
            start_dt = parse_iso_datetime(occurred_at_str)
        except Exception:
            continue

        start_dt = max(start_dt, day_start)
        start_dt = min(start_dt, day_end)

        end_dt = start_dt + timedelta(minutes=30)
        end_dt = min(end_dt, day_end)

        if start_dt < end_dt:
            intervals.append((start_dt, end_dt))

    if not intervals:
        return 0.0, total_seconds / 60.0

    intervals.sort(key=lambda x: x[0])

    merged = []
    for start, end in intervals:
        if not merged:
            merged.append([start, end])
        else:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1][1] = max(last_end, end)
            else:
                merged.append([start, end])

    total_active_seconds = sum((end - start).total_seconds() for start, end in merged)
    active_minutes = total_active_seconds / 60.0
    inactive_minutes = max(0.0, total_seconds - total_active_seconds) / 60.0

    return round(active_minutes, 2), round(inactive_minutes, 2)


def get_dashboard_home(now: Optional[datetime] = None) -> dict:
    if now is None:
        now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    this_month_str = now.strftime("%Y-%m")

    # This month summary
    this_month_summary = summary_store.get_summary_by_period("month", this_month_str)

    # Latest weekly summary
    conn = get_db_connection()
    latest_week_summary = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM summaries WHERE period_type = 'week' ORDER BY period_key DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            latest_week_summary = summary_store.get_summary_by_id(
                row["summary_id"], conn=conn
            )
    finally:
        conn.close()

    # Yesterday's summary
    yesterday_summary = summary_store.get_summary_by_period("day", yesterday_str)

    # Today's activity
    today_logs = activity_store.get_activities_by_date(today_str)
    mapped_logs = []
    for log in today_logs:
        mapped_logs.append(
            {
                "activity_id": log.get("activity_id"),
                "occurred_at": log.get("occurred_at"),
                "app_name": log.get("app_name"),
                "window_title": log.get("window_title"),
                "summary": log.get("summary"),
                "category": log.get("category"),
                "keywords": log.get("keywords") or [],
            }
        )

    active_mins, inactive_mins = get_day_activity_times(today_logs, today_str, now)

    return {
        "this_month_summary": this_month_summary,
        "latest_week_summary": latest_week_summary,
        "yesterday_summary": yesterday_summary,
        "today_activity": {
            "date": today_str,
            "active_minutes": active_mins,
            "inactive_minutes": inactive_mins,
            "logs": mapped_logs,
        },
    }


def find_selectable_years() -> list[str]:
    conn = get_db_connection()
    years = set()
    try:
        cursor = conn.cursor()
        # From summaries
        cursor.execute("SELECT DISTINCT period_key FROM summaries")
        for row in cursor.fetchall():
            key = row[0]
            if len(key) >= 4 and key[:4].isdigit():
                years.add(key[:4])
        # From activity_logs
        cursor.execute("SELECT DISTINCT activity_date FROM activity_logs")
        for row in cursor.fetchall():
            key = row[0]
            if len(key) >= 4 and key[:4].isdigit():
                years.add(key[:4])
    finally:
        conn.close()

    if not years:
        return [datetime.now().strftime("%Y")]
    return sorted(list(years), reverse=True)


def get_dashboard_browse(
    year: Optional[str] = None,
    month: Optional[str] = None,
) -> dict:
    selectable_years = find_selectable_years()

    if year is None and month is None:
        selected_year = selectable_years[0]
    elif month is not None:
        selected_year = month.split("-")[0]
        if year is not None and year != selected_year:
            raise ValueError("Year and Month do not match")
    else:
        selected_year = year

    # Selection mode
    if month is None:
        # Year-level browse
        selected_start = f"{selected_year}-01-01"
        selected_end = f"{selected_year}-12-31"

        # Month summaries in that year
        conn = get_db_connection()
        months_summaries = []
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM summaries WHERE period_type = 'month' AND period_key LIKE ? ORDER BY period_key DESC",
                (f"{selected_year}-%",),
            )
            rows = cursor.fetchall()
            for r in rows:
                months_summaries.append(
                    summary_store.get_summary_by_id(r["summary_id"], conn=conn)
                )
        finally:
            conn.close()

        # Weeks overlapping that year
        all_weeks = summary_store.list_summaries(period_type="week")
        overlapping_weeks = []
        for w in all_weeks:
            p_start = w.get("period_start")
            p_end = w.get("period_end")
            if p_start and p_end:
                if p_start <= selected_end and p_end >= selected_start:
                    overlapping_weeks.append(w)

        overlapping_weeks.sort(key=lambda x: x.get("period_key", ""), reverse=True)

        return {
            "selectable_years": selectable_years,
            "selected_year": selected_year,
            "selected_month": None,
            "months": months_summaries,
            "weeks": overlapping_weeks,
            "days": [],
        }
    else:
        # Month-level browse
        yr, mn = map(int, month.split("-"))
        _, last_day = calendar.monthrange(yr, mn)
        selected_start = f"{month}-01"
        selected_end = f"{month}-{last_day:02d}"

        # Weeks overlapping that month
        all_weeks = summary_store.list_summaries(period_type="week")
        overlapping_weeks = []
        for w in all_weeks:
            p_start = w.get("period_start")
            p_end = w.get("period_end")
            if p_start and p_end:
                if p_start <= selected_end and p_end >= selected_start:
                    overlapping_weeks.append(w)
        overlapping_weeks.sort(key=lambda x: x.get("period_key", ""), reverse=True)

        # Days list with either daily summary or activity logs
        conn = get_db_connection()
        days_data = {}
        try:
            cursor = conn.cursor()
            # Daily summaries in that month
            cursor.execute(
                "SELECT * FROM summaries WHERE period_type = 'day' AND period_key LIKE ? ORDER BY period_key DESC",
                (f"{month}-%",),
            )
            rows = cursor.fetchall()
            for r in rows:
                day_rec = summary_store.get_summary_by_id(r["summary_id"], conn=conn)
                k = day_rec["period_key"]
                days_data[k] = {
                    "date": k,
                    "has_summary": True,
                    "summary_id": day_rec["summary_id"],
                    "summary": day_rec["summary"],
                    "topics": day_rec["topics"] or [],
                }

            # Activity log dates in that month
            cursor.execute(
                "SELECT DISTINCT activity_date FROM activity_logs WHERE activity_date LIKE ? ORDER BY activity_date DESC",
                (f"{month}-%",),
            )
            rows = cursor.fetchall()
            for r in rows:
                k = r[0]
                if k not in days_data:
                    days_data[k] = {
                        "date": k,
                        "has_summary": False,
                        "summary_id": None,
                        "summary": None,
                        "topics": [],
                    }
        finally:
            conn.close()

        sorted_days = [days_data[k] for k in sorted(days_data.keys(), reverse=True)]

        months_summaries = []
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM summaries WHERE period_type = 'month' AND period_key = ?",
                (month,),
            )
            rows = cursor.fetchall()
            for r in rows:
                months_summaries.append(
                    summary_store.get_summary_by_id(r["summary_id"], conn=conn)
                )
        finally:
            conn.close()

        return {
            "selectable_years": selectable_years,
            "selected_year": selected_year,
            "selected_month": month,
            "months": months_summaries,
            "weeks": overlapping_weeks,
            "days": sorted_days,
        }


def get_dashboard_day_details(target_date_str: str) -> dict:
    day_summary = summary_store.get_summary_by_period("day", target_date_str)

    logs = activity_store.get_activities_by_date(target_date_str)
    mapped_logs = []
    for log in logs:
        mapped_logs.append(
            {
                "activity_id": log.get("activity_id"),
                "occurred_at": log.get("occurred_at"),
                "app_name": log.get("app_name"),
                "window_title": log.get("window_title"),
                "summary": log.get("summary"),
                "category": log.get("category"),
                "keywords": log.get("keywords") or [],
            }
        )

    active_mins, inactive_mins = get_day_activity_times(logs, target_date_str)

    return {
        "date": target_date_str,
        "summary": day_summary,
        "active_minutes": active_mins,
        "inactive_minutes": inactive_mins,
        "logs": mapped_logs,
    }


def get_dashboard_stats(
    start_date_str: str,
    end_date_str: str,
) -> dict:
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Invalid date format. Use YYYY-MM-DD")

    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")

    duration = (end_date - start_date).days + 1

    if duration > 3660:
        raise ValueError("Date range exceeds maximum limit of 10 years (3660 days)")

    if duration <= 45:
        granularity = "day"
    elif duration <= 366:
        granularity = "week"
    else:
        granularity = "month"

    all_day_summaries = []
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM summaries WHERE period_type = 'day' AND period_key >= ? AND period_key <= ? ORDER BY period_key ASC",
            (start_date_str, end_date_str),
        )
        rows = cursor.fetchall()
        for r in rows:
            all_day_summaries.append(
                summary_store.get_summary_by_id(r["summary_id"], conn=conn)
            )
    finally:
        conn.close()

    topic_freq = {}
    keyword_freq = {}
    for s in all_day_summaries:
        for t in s.get("topics") or []:
            topic_freq[t] = topic_freq.get(t, 0) + 1
        for k in s.get("keywords") or []:
            keyword_freq[k] = keyword_freq.get(k, 0) + 1

    candidate_topics = [
        t for t, _ in sorted(topic_freq.items(), key=lambda x: x[1], reverse=True)[:20]
    ]
    candidate_keywords = [
        k
        for k, _ in sorted(keyword_freq.items(), key=lambda x: x[1], reverse=True)[:20]
    ]

    buckets_by_key = {}

    curr = start_date
    date_list = []
    while curr <= end_date:
        date_list.append(curr)
        curr += timedelta(days=1)

    for d in date_list:
        d_str = d.strftime("%Y-%m-%d")
        if granularity == "day":
            b_key = d_str
            b_start = d_str
            b_end = d_str
            b_label = d.strftime("%m/%d")
        elif granularity == "week":
            iso_yr, iso_wk, _ = d.isocalendar()
            b_key = f"{iso_yr}-W{iso_wk:02d}"
            mon = d - timedelta(days=d.weekday())
            sun = mon + timedelta(days=6)
            b_start = mon.strftime("%Y-%m-%d")
            b_end = sun.strftime("%Y-%m-%d")
            b_label = f"W{iso_wk:02d}"
        else:  # month
            b_key = d.strftime("%Y-%m")
            _, last_day = calendar.monthrange(d.year, d.month)
            b_start = f"{b_key}-01"
            b_end = f"{b_key}-{last_day:02d}"
            b_label = d.strftime("%Y/%m")

        if b_key not in buckets_by_key:
            buckets_by_key[b_key] = {
                "key": b_key,
                "display_label": b_label,
                "start_date": b_start,
                "end_date": b_end,
                "active_minutes": 0.0,
                "inactive_minutes": 0.0,
                "daily_summary_count": 0,
                "topic_counts": {},
                "keyword_counts": {},
            }

    conn = get_db_connection()
    logs_by_date = {}
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM activity_logs WHERE activity_date >= ? AND activity_date <= ? ORDER BY occurred_at ASC",
            (start_date_str, end_date_str),
        )
        for row in cursor.fetchall():
            act = activity_store.deserialize_activity(row)
            d_str = act["activity_date"]
            if d_str not in logs_by_date:
                logs_by_date[d_str] = []
            logs_by_date[d_str].append(act)
    finally:
        conn.close()

    now_dt = datetime.now()
    for d in date_list:
        d_str = d.strftime("%Y-%m-%d")
        day_logs = logs_by_date.get(d_str, [])
        act_mins, inact_mins = get_day_activity_times(day_logs, d_str, now_dt)

        if granularity == "day":
            b_key = d_str
        elif granularity == "week":
            iso_yr, iso_wk, _ = d.isocalendar()
            b_key = f"{iso_yr}-W{iso_wk:02d}"
        else:  # month
            b_key = d.strftime("%Y-%m")

        b = buckets_by_key[b_key]
        b["active_minutes"] = round(b["active_minutes"] + act_mins, 2)
        b["inactive_minutes"] = round(b["inactive_minutes"] + inact_mins, 2)

    for s in all_day_summaries:
        pk = s["period_key"]
        p_dt = datetime.strptime(pk, "%Y-%m-%d").date()
        if granularity == "day":
            b_key = pk
        elif granularity == "week":
            iso_yr, iso_wk, _ = p_dt.isocalendar()
            b_key = f"{iso_yr}-W{iso_wk:02d}"
        else:
            b_key = p_dt.strftime("%Y-%m")

        if b_key in buckets_by_key:
            b = buckets_by_key[b_key]
            b["daily_summary_count"] += 1

            for t in set(s.get("topics") or []):
                b["topic_counts"][t] = b["topic_counts"].get(t, 0) + 1

            for k in set(s.get("keywords") or []):
                b["keyword_counts"][k] = b["keyword_counts"].get(k, 0) + 1

    sorted_buckets = [buckets_by_key[k] for k in sorted(buckets_by_key.keys())]

    return {
        "granularity": granularity,
        "buckets": sorted_buckets,
        "candidate_topics": candidate_topics,
        "candidate_keywords": candidate_keywords,
    }


class ProjectConflictError(ValueError):
    def __init__(self, message="Conflict: A project with this name already exists."):
        super().__init__(message)


# --- Custom Exception classes for Conflict checks ---


class AliasConflictError(ValueError):
    def __init__(self, existing_person_id: str, existing_person_name: str):
        super().__init__("Conflict: This alias is already confirmed for another person")
        self.existing_person_id = existing_person_id
        self.existing_person_name = existing_person_name


class MainNameConflictError(ValueError):
    def __init__(self, existing_person_id: str, existing_person_name: str):
        super().__init__("Conflict: This name matches another person's normalized name")
        self.existing_person_id = existing_person_id
        self.existing_person_name = existing_person_name


class AssignmentConflictError(ValueError):
    def __init__(
        self,
        message="Conflict: Cannot resolve globally because manual assignments exist for this normalized name",
    ):
        super().__init__(message)


class VaultLinkedPersonError(ValueError):
    def __init__(self, message="Conflict: Vault-linked people cannot be edited."):
        super().__init__(message)


# --- Project Management Services ---

def deserialize_project(row: dict | sqlite3.Row) -> dict:
    p = dict(row)
    kw = p.get("keywords")
    if isinstance(kw, str):
        try:
            p["keywords"] = json.loads(kw)
        except Exception:
            p["keywords"] = []
    elif not isinstance(kw, list):
        p["keywords"] = []
    return p


def deserialize_candidate(row: dict | sqlite3.Row) -> dict:
    c = dict(row)
    kw = c.get("keywords")
    if isinstance(kw, str):
        try:
            c["keywords"] = json.loads(kw)
        except Exception:
            c["keywords"] = []
    elif not isinstance(kw, list):
        c["keywords"] = []
    return c


def list_projects(
    domain: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sql = """
            SELECT p.*, COUNT(sp.summary_id) AS summary_count
            FROM projects p
            LEFT JOIN summary_projects sp ON p.project_id = sp.project_id
            WHERE 1=1
        """
        params = []
        if domain:
            sql += " AND p.domain = ?"
            params.append(domain)
        if status:
            sql += " AND p.status = ?"
            params.append(status)

        sql += """
            GROUP BY p.project_id
            ORDER BY summary_count DESC, p.updated_at DESC
        """
        cursor.execute(sql, params)
        return [deserialize_project(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def create_project(body: schemas.ProjectCreateRequest) -> dict:
    from obsidian_ai_hub.summary.store import normalize_entity_name

    display_name = body.display_name.strip()
    if not display_name:
        raise ValueError("Project name cannot be empty")
    norm_name = normalize_entity_name(display_name)

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            # Conflict check
            cursor.execute("SELECT project_id FROM projects WHERE normalized_name = ?", (norm_name,))
            if cursor.fetchone() is not None:
                raise ProjectConflictError()

            now_iso = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO projects (
                    normalized_name, display_name, domain, status, goal, description,
                    keywords, start_date, target_date, completed_date, project_path,
                    reference_url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                norm_name, display_name, body.domain, body.status, body.goal, body.description,
                json.dumps(body.keywords, ensure_ascii=False), body.start_date, body.target_date,
                body.completed_date, body.project_path, body.reference_url, now_iso, now_iso
            ))
            project_id = cursor.lastrowid

        return get_project_detail(project_id)
    finally:
        conn.close()


def get_project_detail(project_id: int) -> Optional[dict]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        p = deserialize_project(row)

        cursor.execute("""
            SELECT s.summary_id, s.period_type, s.period_key
            FROM summary_projects sp
            JOIN summaries s ON sp.summary_id = s.summary_id
            WHERE sp.project_id = ?
            ORDER BY s.period_start DESC, s.period_key DESC
        """, (project_id,))
        p["summaries"] = [dict(r) for r in cursor.fetchall()]
        p["summary_count"] = len(p["summaries"])
        return p
    finally:
        conn.close()


def update_project(project_id: int, body: schemas.ProjectUpdateRequest) -> dict:
    from obsidian_ai_hub.summary.store import normalize_entity_name

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
            row = cursor.fetchone()
            if row is None:
                raise FileNotFoundError("Project not found")

            p = deserialize_project(row)
            updates = []
            params = []

            if body.display_name is not None:
                display_name = body.display_name.strip()
                if not display_name:
                    raise ValueError("Project name cannot be empty")
                norm_name = normalize_entity_name(display_name)
                # Conflict check
                cursor.execute("SELECT project_id FROM projects WHERE normalized_name = ? AND project_id != ?", (norm_name, project_id))
                if cursor.fetchone() is not None:
                    raise ProjectConflictError()
                updates.append("display_name = ?")
                params.append(display_name)
                updates.append("normalized_name = ?")
                params.append(norm_name)

            if body.domain is not None:
                updates.append("domain = ?")
                params.append(body.domain)

            if body.status is not None:
                updates.append("status = ?")
                params.append(body.status)

            if body.goal is not None:
                updates.append("goal = ?")
                params.append(body.goal)

            if body.description is not None:
                updates.append("description = ?")
                params.append(body.description)

            if body.keywords is not None:
                updates.append("keywords = ?")
                params.append(json.dumps(body.keywords, ensure_ascii=False))

            if body.start_date is not None:
                updates.append("start_date = ?")
                params.append(body.start_date)

            if body.target_date is not None:
                updates.append("target_date = ?")
                params.append(body.target_date)

            if body.completed_date is not None:
                updates.append("completed_date = ?")
                params.append(body.completed_date)

            if body.project_path is not None:
                updates.append("project_path = ?")
                params.append(body.project_path)

            if body.reference_url is not None:
                updates.append("reference_url = ?")
                params.append(body.reference_url)

            if updates:
                now_iso = datetime.now().isoformat()
                updates.append("updated_at = ?")
                params.append(now_iso)

                sql = f"UPDATE projects SET {', '.join(updates)} WHERE project_id = ?"
                params.append(project_id)
                cursor.execute(sql, tuple(params))

        return get_project_detail(project_id)
    finally:
        conn.close()


def list_project_candidates(status: Optional[str] = "unresolved") -> list[dict]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sql = "SELECT * FROM project_candidates WHERE 1=1"
        params = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        cursor.execute(sql, params)
        return [deserialize_candidate(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_project_candidate_detail(candidate_id: int) -> Optional[dict]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM project_candidates WHERE candidate_id = ?", (candidate_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        c = deserialize_candidate(row)

        cursor.execute("""
            SELECT s.summary_id, s.period_type, s.period_key
            FROM summary_project_candidates spc
            JOIN summaries s ON spc.summary_id = s.summary_id
            WHERE spc.candidate_id = ?
            ORDER BY s.period_start DESC, s.period_key DESC
        """, (candidate_id,))
        c["summaries"] = [dict(r) for r in cursor.fetchall()]
        c["assigned_summaries_count"] = len(c["summaries"])
        return c
    finally:
        conn.close()


def resolve_project_candidate(
    candidate_id: int,
    body: schemas.ProjectCandidateResolveRequest,
) -> dict:
    from obsidian_ai_hub.summary.store import normalize_entity_name

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM project_candidates WHERE candidate_id = ?", (candidate_id,))
            row = cursor.fetchone()
            if row is None:
                raise FileNotFoundError("Candidate not found")

            c = deserialize_candidate(row)

            # 1. Reject action
            if body.action == "reject":
                conn.execute("UPDATE project_candidates SET status = 'rejected', updated_at = ? WHERE candidate_id = ?", (datetime.now().isoformat(), candidate_id))
                conn.execute("DELETE FROM summary_project_candidates WHERE candidate_id = ?", (candidate_id,))

            # 2. Reopen rejected action
            elif body.action == "reopen_rejected":
                conn.execute("UPDATE project_candidates SET status = 'unresolved', updated_at = ? WHERE candidate_id = ?", (datetime.now().isoformat(), candidate_id))

            # 3. Approve new action
            elif body.action == "approve_new":
                display_name = body.display_name.strip() if body.display_name is not None else c["display_name"]
                if not display_name:
                    raise ValueError("Project name cannot be empty")
                norm_name = normalize_entity_name(display_name)

                # Conflict check
                cursor.execute("SELECT project_id FROM projects WHERE normalized_name = ?", (norm_name,))
                if cursor.fetchone() is not None:
                    raise ProjectConflictError()

                domain = body.domain if body.domain is not None else c["domain"]
                status = body.status if body.status is not None else "inquiry"
                goal = body.goal if body.goal is not None else c["goal"]
                description = body.description if body.description is not None else c["description"]
                keywords = body.keywords if body.keywords is not None else c["keywords"]
                start_date = body.start_date if body.start_date is not None else c["start_date"]
                target_date = body.target_date if body.target_date is not None else c["target_date"]
                completed_date = body.completed_date if body.completed_date is not None else c["completed_date"]
                project_path = body.project_path if body.project_path is not None else c.get("project_path")
                reference_url = body.reference_url if body.reference_url is not None else c.get("reference_url")

                now_iso = datetime.now().isoformat()
                cursor.execute("""
                    INSERT INTO projects (
                        normalized_name, display_name, domain, status, goal, description,
                        keywords, start_date, target_date, completed_date, project_path,
                        reference_url, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    norm_name, display_name, domain, status, goal, description,
                    json.dumps(keywords, ensure_ascii=False), start_date, target_date,
                    completed_date, project_path, reference_url, now_iso, now_iso
                ))
                project_id = cursor.lastrowid

                # Migrate all summary links to summary_projects
                cursor.execute("SELECT summary_id, display_order FROM summary_project_candidates WHERE candidate_id = ?", (candidate_id,))
                links = cursor.fetchall()
                for link in links:
                    conn.execute("""
                        INSERT OR IGNORE INTO summary_projects (summary_id, project_id, display_order)
                        VALUES (?, ?, ?)
                    """, (link["summary_id"], project_id, link["display_order"]))

                # Clean up candidate summary links
                conn.execute("DELETE FROM summary_project_candidates WHERE candidate_id = ?", (candidate_id,))
                # Set candidate resolved
                conn.execute("UPDATE project_candidates SET status = 'resolved', updated_at = ? WHERE candidate_id = ?", (now_iso, candidate_id))

            # 4. Link existing action
            elif body.action == "link_existing":
                project_id = body.target_project_id
                if project_id is None:
                    raise ValueError("target_project_id is required for link_existing")

                cursor.execute("SELECT project_id FROM projects WHERE project_id = ?", (project_id,))
                if cursor.fetchone() is None:
                    raise ValueError("Target project not found")

                now_iso = datetime.now().isoformat()
                # Migrate all summary links to summary_projects
                cursor.execute("SELECT summary_id, display_order FROM summary_project_candidates WHERE candidate_id = ?", (candidate_id,))
                links = cursor.fetchall()
                for link in links:
                    conn.execute("""
                        INSERT OR IGNORE INTO summary_projects (summary_id, project_id, display_order)
                        VALUES (?, ?, ?)
                    """, (link["summary_id"], project_id, link["display_order"]))

                # Clean up candidate summary links
                conn.execute("DELETE FROM summary_project_candidates WHERE candidate_id = ?", (candidate_id,))
                # Set candidate resolved
                conn.execute("UPDATE project_candidates SET status = 'resolved', updated_at = ? WHERE candidate_id = ?", (now_iso, candidate_id))

        return {"success": True}
    finally:
        conn.close()


# --- People Management services ---


def list_people() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.person_id, p.display_name, p.normalized_name, p.vault_id, COUNT(sp.summary_id) AS summary_count
            FROM people p
            LEFT JOIN summary_people sp ON p.person_id = sp.person_id
            GROUP BY p.person_id, p.display_name, p.normalized_name, p.vault_id
            ORDER BY summary_count DESC, p.display_name ASC, p.person_id ASC
        """)
        people_rows = [dict(r) for r in cursor.fetchall()]

        for p in people_rows:
            cursor.execute(
                "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
                (p["person_id"],),
            )
            p["aliases"] = [dict(r) for r in cursor.fetchall()]
        return people_rows
    finally:
        conn.close()


def get_person_detail(person_id: str) -> Optional[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
            (person_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        p = dict(row)

        cursor.execute(
            "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
            (p["person_id"],),
        )
        p["aliases"] = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            """
            SELECT s.summary_id, s.period_type, s.period_key, sp.note, sp.display_order
            FROM summary_people sp
            JOIN summaries s ON sp.summary_id = s.summary_id
            WHERE sp.person_id = ?
            ORDER BY s.period_start DESC, s.period_key DESC
            """,
            (person_id,),
        )
        p["summaries"] = [dict(r) for r in cursor.fetchall()]

        # Compute counts
        cursor.execute(
            "SELECT COUNT(*) FROM summary_people WHERE person_id = ?", (person_id,)
        )
        summaries_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM person_aliases WHERE person_id = ?", (person_id,)
        )
        aliases_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM summary_person_assignments WHERE person_id = ?",
            (person_id,),
        )
        assignments_count = cursor.fetchone()[0]

        p["summary_count"] = summaries_count
        p["relation_counts"] = {
            "summaries": summaries_count,
            "aliases": aliases_count,
            "assignments": assignments_count,
        }

        return p
    finally:
        conn.close()


def update_unlinked_person(
    person_id: str,
    display_name: Optional[str] = None,
    aliases: Optional[list[str]] = None,
) -> dict:
    from obsidian_ai_hub.summary.store import normalize_entity_name

    if display_name is None and aliases is None:
        raise ValueError(
            "At least display_name or aliases must be specified for update."
        )

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # 1. Fetch current person row
            cursor.execute(
                "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
                (person_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise FileNotFoundError("Person not found")
            person = dict(row)

            # Reject if Vault-linked
            if person.get("vault_id") is not None:
                raise VaultLinkedPersonError()

            # Load current aliases for self-conflict exclusion
            cursor.execute(
                "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
                (person_id,),
            )
            current_aliases = [dict(r) for r in cursor.fetchall()]
            current_names = {person["normalized_name"]} | {
                a["normalized_name"] for a in current_aliases
            }

            # 2. Determine target main name and aliases
            target_display_name = person["display_name"]
            target_normalized_name = person["normalized_name"]

            if display_name is not None:
                stripped_display_name = display_name.strip()
                if not stripped_display_name:
                    raise ValueError("表示名に空文字を指定することはできません。")
                target_display_name = stripped_display_name
                target_normalized_name = normalize_entity_name(stripped_display_name)

            target_aliases = []
            if aliases is not None:
                seen_norm_aliases = set()
                for alias in aliases:
                    stripped_alias = alias.strip()
                    if not stripped_alias:
                        raise ValueError("別名に空文字を指定することはできません。")
                    norm_alias = normalize_entity_name(stripped_alias)
                    if norm_alias in seen_norm_aliases:
                        raise ValueError("重複した別名を指定することはできません。")
                    seen_norm_aliases.add(norm_alias)
                    target_aliases.append(
                        {"normalized_name": norm_alias, "display_name": stripped_alias}
                    )
            else:
                # Keep current aliases
                target_aliases = current_aliases

            # 3. Conflict checks
            names_to_check = [target_normalized_name] + [
                a["normalized_name"] for a in target_aliases
            ]

            for name_to_check in names_to_check:
                # Conflict with another person's main name
                cursor.execute(
                    "SELECT person_id, display_name FROM people WHERE normalized_name = ? AND person_id != ?",
                    (name_to_check, person_id),
                )
                other_main = cursor.fetchone()
                if other_main is not None:
                    raise MainNameConflictError(
                        other_main["person_id"], other_main["display_name"]
                    )

                # Conflict with another person's alias
                cursor.execute(
                    "SELECT person_id, display_name FROM person_aliases WHERE normalized_name = ? AND person_id != ?",
                    (name_to_check, person_id),
                )
                other_alias = cursor.fetchone()
                if other_alias is not None:
                    raise AliasConflictError(
                        other_alias["person_id"], other_alias["display_name"]
                    )

                # Conflict with manual assignments (only newly specified)
                if name_to_check not in current_names:
                    cursor.execute(
                        "SELECT COUNT(*) FROM summary_person_assignments WHERE normalized_name = ?",
                        (name_to_check,),
                    )
                    if cursor.fetchone()[0] > 0:
                        raise AssignmentConflictError()

            # 4. Apply changes
            conn.execute(
                "UPDATE people SET display_name = ?, normalized_name = ? WHERE person_id = ?",
                (target_display_name, target_normalized_name, person_id),
            )

            if aliases is not None:
                conn.execute(
                    "DELETE FROM person_aliases WHERE person_id = ?", (person_id,)
                )
                for ta in target_aliases:
                    conn.execute(
                        "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
                        (ta["normalized_name"], person_id, ta["display_name"]),
                    )

        # On success, return updated person detail
        return get_person_detail(person_id)
    finally:
        conn.close()


def delete_person(person_id: str) -> dict:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT person_id FROM people WHERE person_id = ?", (person_id,)
            )
            if cursor.fetchone() is None:
                raise FileNotFoundError("Person not found")

            cursor.execute(
                "DELETE FROM summary_people WHERE person_id = ?", (person_id,)
            )
            deleted_summary_people = cursor.rowcount

            cursor.execute(
                "DELETE FROM person_aliases WHERE person_id = ?", (person_id,)
            )
            deleted_aliases = cursor.rowcount

            cursor.execute(
                "DELETE FROM summary_person_assignments WHERE person_id = ?",
                (person_id,),
            )
            deleted_assignments = cursor.rowcount

            cursor.execute("DELETE FROM people WHERE person_id = ?", (person_id,))

            return {
                "success": True,
                "deleted_summary_people": deleted_summary_people,
                "deleted_aliases": deleted_aliases,
                "deleted_assignments": deleted_assignments,
            }
    finally:
        conn.close()


def list_person_candidates() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT candidate_id, display_name, normalized_name, status FROM person_candidates"
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_person_candidate_detail(candidate_id: str) -> Optional[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT candidate_id, display_name, normalized_name, status FROM person_candidates WHERE candidate_id = ?",
            (candidate_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        c = dict(row)

        cursor.execute(
            """
            SELECT s.summary_id, s.period_type, s.period_key, spc.note, spc.display_order
            FROM summary_person_candidates spc
            JOIN summaries s ON spc.summary_id = s.summary_id
            WHERE spc.candidate_id = ?
            ORDER BY s.period_start DESC, s.period_key DESC
            """,
            (candidate_id,),
        )
        c["summaries"] = [dict(r) for r in cursor.fetchall()]

        # Get assigned summaries count
        cursor.execute(
            "SELECT COUNT(*) FROM summary_person_assignments WHERE normalized_name = ?",
            (c["normalized_name"],),
        )
        c["assigned_summaries_count"] = cursor.fetchone()[0]

        return c
    finally:
        conn.close()


def assign_candidate_summary(
    candidate_id: str, summary_id: str, target_person_id: str
) -> bool:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # 1. Fetch candidate to identify normalized_name
            cursor.execute(
                "SELECT candidate_id, display_name, normalized_name FROM person_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            cand_row = cursor.fetchone()
            if cand_row is None:
                raise FileNotFoundError("Candidate not found")
            cand = dict(cand_row)
            normalized_name = cand["normalized_name"]

            # 2. Check if candidate-summary link exists
            cursor.execute(
                "SELECT note, display_order FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                (summary_id, candidate_id),
            )
            link_row = cursor.fetchone()
            if link_row is None:
                raise FileNotFoundError("Candidate summary link not found")
            cand_note = link_row["note"]
            cand_order = link_row["display_order"]

            # 3. Check target person existence and vault-linked constraint
            cursor.execute(
                "SELECT person_id, display_name, vault_id FROM people WHERE person_id = ?",
                (target_person_id,),
            )
            target_row = cursor.fetchone()
            if target_row is None:
                raise ValueError("Target person not found")
            target = dict(target_row)
            if not target.get("vault_id"):
                raise ValueError("割当先はVault連携済み人物のみに限定されています。")

            # 4. Remove candidate's link from summary_person_candidates
            conn.execute(
                "DELETE FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                (summary_id, candidate_id),
            )

            # 5. Insert/Save manual assignment to summary_person_assignments
            conn.execute(
                """
                INSERT OR REPLACE INTO summary_person_assignments (summary_id, normalized_name, person_id)
                VALUES (?, ?, ?)
                """,
                (summary_id, normalized_name, target_person_id),
            )

            # 6. Insert or merge/concatenate notes and display order in summary_people
            cursor.execute(
                "SELECT note, display_order FROM summary_people WHERE summary_id = ? AND person_id = ?",
                (summary_id, target_person_id),
            )
            existing_link = cursor.fetchone()

            if existing_link is not None:
                notes_to_join = []
                existing_note = existing_link["note"]
                existing_order = existing_link["display_order"]

                if existing_note and existing_note.strip():
                    notes_to_join.append(existing_note.strip())
                if cand_note and cand_note.strip():
                    notes_to_join.append(cand_note.strip())

                merged_note = "\n".join(notes_to_join) if notes_to_join else None
                merged_order = merge_display_orders(existing_order, cand_order)

                conn.execute(
                    "UPDATE summary_people SET note = ?, display_order = ? WHERE summary_id = ? AND person_id = ?",
                    (merged_note, merged_order, summary_id, target_person_id),
                )
            else:
                conn.execute(
                    "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                    (summary_id, target_person_id, cand_note, cand_order),
                )

            # 7. Delete the candidate if no remaining links exist
            cursor.execute(
                "SELECT COUNT(*) FROM summary_person_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            remaining_links_count = cursor.fetchone()[0]
            if remaining_links_count == 0:
                conn.execute(
                    "DELETE FROM person_candidates WHERE candidate_id = ?",
                    (candidate_id,),
                )

            return True
    finally:
        conn.close()


def resolve_person_candidate(
    candidate_id: str, target_person_id: str
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # 1. Fetch candidate
            cursor.execute(
                "SELECT candidate_id, display_name, normalized_name, status FROM person_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            cand_row = cursor.fetchone()
            if cand_row is None:
                raise ValueError("Candidate not found")
            cand = dict(cand_row)

            # 1b. Check if there are any manual assignments for this candidate's normalized_name
            cursor.execute(
                "SELECT COUNT(*) FROM summary_person_assignments WHERE normalized_name = ?",
                (cand["normalized_name"],),
            )
            assigned_count = cursor.fetchone()[0]
            if assigned_count > 0:
                raise AssignmentConflictError()

            # 2. Fetch target person
            cursor.execute(
                "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
                (target_person_id,),
            )
            target_row = cursor.fetchone()
            if target_row is None:
                raise ValueError("Target person not found")
            target = dict(target_row)

            # Enforce target must be a Vault-linked person
            if not target.get("vault_id"):
                raise ValueError(
                    "未連携人物への解決は許可されていません。解決先はVault連携済みの人物だけに制限されています。"
                )

            normalized_name = cand["normalized_name"]

            # 3. Conflict check 1: person_aliases
            cursor.execute(
                "SELECT person_id, display_name FROM person_aliases WHERE normalized_name = ?",
                (normalized_name,),
            )
            alias_row = cursor.fetchone()
            if alias_row is not None and alias_row["person_id"] != target_person_id:
                raise AliasConflictError(
                    alias_row["person_id"], alias_row["display_name"]
                )

            # 4. Conflict check 2: people.normalized_name
            cursor.execute(
                "SELECT person_id, display_name FROM people WHERE normalized_name = ?",
                (normalized_name,),
            )
            main_name_row = cursor.fetchone()
            if (
                main_name_row is not None
                and main_name_row["person_id"] != target_person_id
            ):
                raise MainNameConflictError(
                    main_name_row["person_id"], main_name_row["display_name"]
                )

            # 5. Insert alias (Ensure we do a normal INSERT only if alias_row is None and raise error on fail)
            if alias_row is None:
                conn.execute(
                    "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
                    (normalized_name, target_person_id, cand["display_name"]),
                )

            # 6. Migrate summaries
            cursor.execute(
                "SELECT summary_id, note, display_order FROM summary_person_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            links = cursor.fetchall()

            for link in links:
                summary_id = link["summary_id"]
                cand_note = link["note"]
                cand_order = link["display_order"]

                cursor.execute(
                    "SELECT note, display_order FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, target_person_id),
                )
                existing_link = cursor.fetchone()

                if existing_link is not None:
                    notes_to_join = []
                    existing_note = existing_link["note"]
                    existing_order = existing_link["display_order"]

                    if existing_note and existing_note.strip():
                        notes_to_join.append(existing_note.strip())
                    if cand_note and cand_note.strip():
                        notes_to_join.append(cand_note.strip())

                    merged_note = "\n".join(notes_to_join) if notes_to_join else None
                    merged_order = merge_display_orders(existing_order, cand_order)

                    conn.execute(
                        "UPDATE summary_people SET note = ?, display_order = ? WHERE summary_id = ? AND person_id = ?",
                        (merged_note, merged_order, summary_id, target_person_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, target_person_id, cand_note, cand_order),
                    )

                conn.execute(
                    "DELETE FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                    (summary_id, candidate_id),
                )

            # 7. Delete candidate
            conn.execute(
                "DELETE FROM person_candidates WHERE candidate_id = ?", (candidate_id,)
            )

            return {"success": True}
    finally:
        conn.close()


def get_duplicate_candidates() -> dict[str, Any]:
    safe_map, report = load_people_notes_with_report()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Group 1: Unlinked people matching safe Vault input
        cursor.execute(
            "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE vault_id IS NULL"
        )
        unlinked_people = [dict(r) for r in cursor.fetchall()]

        vault_matches = []
        for p in unlinked_people:
            norm = p["normalized_name"]
            if norm in safe_map:
                v_note = safe_map[norm]
                vault_matches.append(
                    {
                        "unlinked_person": p,
                        "vault_person": {
                            "id": v_note["id"],
                            "name": v_note["name"],
                            "path": str(v_note["file_path"]),
                        },
                    }
                )

        # Group 2: Same non-NULL vault_id across multiple people records
        cursor.execute(
            """
            SELECT vault_id, count(*) as cnt
            FROM people
            WHERE vault_id IS NOT NULL
            GROUP BY vault_id
            HAVING cnt > 1
            """
        )
        duplicate_vault_ids = [r["vault_id"] for r in cursor.fetchall()]

        same_vault_id_groups = []
        for v_id in duplicate_vault_ids:
            cursor.execute(
                "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE vault_id = ?",
                (v_id,),
            )
            members = [dict(r) for r in cursor.fetchall()]
            same_vault_id_groups.append({"vault_id": v_id, "people": members})

        return {
            "vault_matches": vault_matches,
            "same_vault_id_groups": same_vault_id_groups,
        }
    finally:
        conn.close()


def consolidate_summary_links(
    from_note: Optional[str],
    to_note: Optional[str],
    from_order: Optional[int],
    to_order: Optional[int],
) -> tuple[Optional[str], Optional[int]]:
    notes_to_join = []
    if to_note and to_note.strip():
        notes_to_join.append(to_note.strip())
    if from_note and from_note.strip():
        notes_to_join.append(from_note.strip())
    merged_note = "\n".join(notes_to_join) if notes_to_join else None
    merged_order = merge_display_orders(to_order, from_order)
    return merged_note, merged_order


def verify_people_merge(
    cursor: sqlite3.Cursor, from_person_id: str, to_person_id: str
) -> dict:
    if from_person_id == to_person_id:
        return {
            "allowed": False,
            "reason": "統合元と統合主に同じ人物が指定されています。",
            "transferred_summaries_count": 0,
            "transferred_aliases_count": 0,
            "alias_transfers": [],
            "merged_summaries": [],
        }

    # 1. Fetch people
    cursor.execute(
        "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
        (from_person_id,),
    )
    from_row = cursor.fetchone()
    if from_row is None:
        return {
            "allowed": False,
            "reason": "統合元の人物が見つかりません。",
            "transferred_summaries_count": 0,
            "transferred_aliases_count": 0,
            "alias_transfers": [],
            "merged_summaries": [],
        }
    from_p = dict(from_row)

    cursor.execute(
        "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
        (to_person_id,),
    )
    to_row = cursor.fetchone()
    if to_row is None:
        return {
            "allowed": False,
            "reason": "統合先の人物が見つかりません。",
            "from_person": from_p,
            "transferred_summaries_count": 0,
            "transferred_aliases_count": 0,
            "alias_transfers": [],
            "merged_summaries": [],
        }
    to_p = dict(to_row)

    # 2. Get aliases
    cursor.execute(
        "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
        (from_person_id,),
    )
    from_aliases = [dict(r) for r in cursor.fetchall()]
    from_p["aliases"] = from_aliases

    cursor.execute(
        "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
        (to_person_id,),
    )
    to_aliases = [dict(r) for r in cursor.fetchall()]
    to_p["aliases"] = to_aliases

    # 3. Vault ID verification
    from_vault = from_p.get("vault_id")
    to_vault = to_p.get("vault_id")

    # Reject Vault-linked to Unlinked
    if from_vault is not None and to_vault is None:
        return {
            "allowed": False,
            "reason": "Vault連携済み人物を未連携人物へ寄せる操作は拒否されます。",
            "from_person": from_p,
            "to_person": to_p,
            "transferred_summaries_count": 0,
            "transferred_aliases_count": 0,
            "alias_transfers": [],
            "merged_summaries": [],
        }

    # Reject different vault_id values
    if from_vault is not None and to_vault is not None and from_vault != to_vault:
        return {
            "allowed": False,
            "reason": "異なるVault IDを持つ人物同士の統合は拒否されます。",
            "from_person": from_p,
            "to_person": to_p,
            "transferred_summaries_count": 0,
            "transferred_aliases_count": 0,
            "alias_transfers": [],
            "merged_summaries": [],
        }

    # 4. Third-party conflict check
    # Gather the set of normalized names that would be transferred
    source_names = {from_p["normalized_name"]} | {
        a["normalized_name"] for a in from_aliases
    }

    if source_names:
        placeholders = ", ".join("?" for _ in source_names)

        # Check conflicts with third-party main name
        cursor.execute(
            f"SELECT person_id, display_name, normalized_name FROM people WHERE normalized_name IN ({placeholders}) AND person_id NOT IN (?, ?)",
            list(source_names) + [from_person_id, to_person_id],
        )
        conflicting_people = cursor.fetchall()
        if conflicting_people:
            names_str = ", ".join(r["display_name"] for r in conflicting_people)
            return {
                "allowed": False,
                "reason": f"統合元の名前または別名が、第三者の正規名と衝突しています（衝突対象: {names_str}）。",
                "from_person": from_p,
                "to_person": to_p,
                "transferred_summaries_count": 0,
                "transferred_aliases_count": 0,
                "alias_transfers": [],
                "merged_summaries": [],
            }

        # Check conflicts with third-party aliases
        cursor.execute(
            f"SELECT person_id, display_name, normalized_name FROM person_aliases WHERE normalized_name IN ({placeholders}) AND person_id NOT IN (?, ?)",
            list(source_names) + [from_person_id, to_person_id],
        )
        conflicting_aliases = cursor.fetchall()
        if conflicting_aliases:
            names_str = ", ".join(r["display_name"] for r in conflicting_aliases)
            return {
                "allowed": False,
                "reason": f"統合元の名前または別名が、第三者の別名と衝突しています（衝突対象: {names_str}）。",
                "from_person": from_p,
                "to_person": to_p,
                "transferred_summaries_count": 0,
                "transferred_aliases_count": 0,
                "alias_transfers": [],
                "merged_summaries": [],
            }

    # 5. Build Alias Transfers Preview
    alias_transfers = []
    seen_normalized = {a["normalized_name"] for a in to_aliases} | {
        to_p["normalized_name"]
    }

    for fa in from_aliases:
        norm = fa["normalized_name"]
        if norm not in seen_normalized:
            alias_transfers.append(
                {"normalized_name": norm, "display_name": fa["display_name"]}
            )
            seen_normalized.add(norm)

    from_p_norm = from_p["normalized_name"]
    if from_p_norm not in seen_normalized:
        alias_transfers.append(
            {"normalized_name": from_p_norm, "display_name": from_p["display_name"]}
        )

    # 6. Build Merged Summaries Preview
    cursor.execute(
        "SELECT summary_id, note, display_order FROM summary_people WHERE person_id = ?",
        (from_person_id,),
    )
    from_links = {r["summary_id"]: dict(r) for r in cursor.fetchall()}

    cursor.execute(
        "SELECT summary_id, note, display_order FROM summary_people WHERE person_id = ?",
        (to_person_id,),
    )
    to_links = {r["summary_id"]: dict(r) for r in cursor.fetchall()}

    merged_summaries = []
    for summary_id, from_link in from_links.items():
        if summary_id in to_links:
            to_link = to_links[summary_id]

            # Fetch summary details
            cursor.execute(
                "SELECT period_key, period_type FROM summaries WHERE summary_id = ?",
                (summary_id,),
            )
            sum_row = cursor.fetchone()
            if sum_row:
                period_key = sum_row["period_key"]
                period_type = sum_row["period_type"]
            else:
                period_key = "unknown"
                period_type = "unknown"

            from_note = from_link["note"]
            to_note = to_link["note"]

            merged_note, merged_display_order = consolidate_summary_links(
                from_note, to_note, from_link["display_order"], to_link["display_order"]
            )

            merged_summaries.append(
                {
                    "summary_id": summary_id,
                    "period_key": period_key,
                    "period_type": period_type,
                    "from_note": from_note,
                    "to_note": to_note,
                    "merged_note": merged_note,
                    "merged_display_order": merged_display_order,
                }
            )

    return {
        "allowed": True,
        "reason": "統合可能です。",
        "from_person": from_p,
        "to_person": to_p,
        "transferred_summaries_count": len(from_links),
        "transferred_aliases_count": len(alias_transfers),
        "alias_transfers": alias_transfers,
        "merged_summaries": merged_summaries,
    }


def preview_people_merge(from_person_id: str, to_person_id: str) -> dict:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        return verify_people_merge(cursor, from_person_id, to_person_id)
    finally:
        conn.close()


def merge_people(from_person_id: str, to_person_id: str) -> bool:
    if from_person_id == to_person_id:
        raise ValueError("Source and target person IDs for merge cannot be identical.")

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # Verify before merge
            preview = verify_people_merge(cursor, from_person_id, to_person_id)
            if not preview["allowed"]:
                raise ValueError(preview["reason"])

            from_p = preview["from_person"]

            # 2. Migrate summary links
            cursor.execute(
                "SELECT summary_id, note, display_order FROM summary_people WHERE person_id = ?",
                (from_person_id,),
            )
            links = cursor.fetchall()

            for link in links:
                summary_id = link["summary_id"]
                note = link["note"]
                order = link["display_order"]

                cursor.execute(
                    "SELECT note, display_order FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, to_person_id),
                )
                existing_link = cursor.fetchone()

                if existing_link is not None:
                    merged_note, merged_order = consolidate_summary_links(
                        note,
                        existing_link["note"],
                        order,
                        existing_link["display_order"],
                    )

                    conn.execute(
                        "UPDATE summary_people SET note = ?, display_order = ? WHERE summary_id = ? AND person_id = ?",
                        (merged_note, merged_order, summary_id, to_person_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, to_person_id, note, order),
                    )

                conn.execute(
                    "DELETE FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, from_person_id),
                )

            # 3. Migrate aliases
            # Migrate only the ones in preview["alias_transfers"], without OR IGNORE, allowing it to fail on unexpected conflict
            from_p_norm = from_p["normalized_name"]
            for al in preview["alias_transfers"]:
                norm = al["normalized_name"]
                disp = al["display_name"]
                if norm == from_p_norm:
                    conn.execute(
                        "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
                        (norm, to_person_id, disp),
                    )
                else:
                    conn.execute(
                        "UPDATE person_aliases SET person_id = ? WHERE normalized_name = ?",
                        (to_person_id, norm),
                    )

            # Delete any remaining aliases under from_person_id
            conn.execute(
                "DELETE FROM person_aliases WHERE person_id = ?", (from_person_id,)
            )

            # 3b. Update summary_person_assignments for from_person_id to to_person_id
            conn.execute(
                "UPDATE OR REPLACE summary_person_assignments SET person_id = ? WHERE person_id = ?",
                (to_person_id, from_person_id),
            )

            # 4. Delete source person
            conn.execute("DELETE FROM people WHERE person_id = ?", (from_person_id,))

            return True
    finally:
        conn.close()


def sync_people() -> dict[str, Any]:
    people_notes_map, report = load_people_notes_with_report()
    parsed_notes = report.get("parsed_notes", [])

    conn = get_db_connection()
    try:
        with conn:
            # 1. Detect conflicts
            db_conflicts = get_db_vault_conflicts_report(conn, parsed_notes)

            # 2. Sync safe part
            from obsidian_ai_hub.people_sync.sync import sync_people_in_tx

            sync_people_in_tx(conn, people_notes_map)

            # Return reports
            clean_loader_report = {
                "file_deficiencies": report.get("file_deficiencies", []),
                "duplicate_ids": report.get("duplicate_ids", []),
                "normalized_name_collisions": report.get(
                    "normalized_name_collisions", []
                ),
                "alias_collisions": report.get("alias_collisions", []),
            }
            return {
                "synced": True,
                "loader_report": clean_loader_report,
                "db_conflicts": db_conflicts,
            }
    finally:
        conn.close()


def get_vault_report_dynamic() -> dict[str, Any]:
    people_notes_map, report = load_people_notes_with_report()
    parsed_notes = report.get("parsed_notes", [])

    conn = get_db_connection()
    try:
        db_conflicts = get_db_vault_conflicts_report(conn, parsed_notes)
        clean_loader_report = {
            "file_deficiencies": report.get("file_deficiencies", []),
            "duplicate_ids": report.get("duplicate_ids", []),
            "normalized_name_collisions": report.get("normalized_name_collisions", []),
            "alias_collisions": report.get("alias_collisions", []),
        }
        return {"loader_report": clean_loader_report, "db_conflicts": db_conflicts}
    finally:
        conn.close()


def delete_person_alias(person_id: str, normalized_name: str) -> dict:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT person_id FROM people WHERE person_id = ?", (person_id,)
            )
            if cursor.fetchone() is None:
                raise FileNotFoundError("Person not found")

            cursor.execute(
                "SELECT normalized_name, display_name FROM person_aliases WHERE normalized_name = ? AND person_id = ?",
                (normalized_name, person_id),
            )
            alias_row = cursor.fetchone()
            if alias_row is None:
                raise FileNotFoundError("Alias not found for this person")

            conn.execute(
                "DELETE FROM person_aliases WHERE normalized_name = ? AND person_id = ?",
                (normalized_name, person_id),
            )

        return get_person_detail(person_id)
    finally:
        conn.close()


def get_edit_options() -> dict:
    from obsidian_ai_hub.utils.topics import TOPIC_ENUM
    from obsidian_ai_hub.summary.store import (
        DAY_ITEM_KINDS,
        WEEK_ITEM_KINDS,
        MONTH_ITEM_KINDS,
    )

    return {
        "topics": list(TOPIC_ENUM),
        "item_kinds": {
            "day": DAY_ITEM_KINDS,
            "week": WEEK_ITEM_KINDS,
            "month": MONTH_ITEM_KINDS,
        },
    }


class TaskConfigConflictError(ValueError):
    def __init__(self, message="Conflict: Task configuration has been updated by another session. Please refresh."):
        super().__init__(message)


def update_summary_detail(summary_id: str, body: schemas.SummaryUpdateRequest) -> dict:
    from obsidian_ai_hub.utils.topics import TOPIC_ENUM
    from obsidian_ai_hub.summary.store import (
        DAY_ITEM_KINDS,
        WEEK_ITEM_KINDS,
        MONTH_ITEM_KINDS,
    )

    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise ValueError("empty payload")

    # Load current summary to check period_type
    current = summary_store.get_summary_by_id(summary_id)
    if current is None:
        raise FileNotFoundError(f"Summary not found: {summary_id}")
    period_type = current["period_type"]

    allowed_kinds = {
        "day": DAY_ITEM_KINDS,
        "week": WEEK_ITEM_KINDS,
        "month": MONTH_ITEM_KINDS,
    }[period_type]

    # Validate summary body
    if "summary" in payload:
        val = payload["summary"]
        if val is not None and not str(val).strip():
            raise ValueError("summary body must not be empty")

    # Validate items
    if "items" in payload:
        raw_items = payload["items"]
        if raw_items is None:
            raw_items = []
        for item in raw_items:
            if item["kind"] not in allowed_kinds:
                raise ValueError(
                    f"Invalid item kind '{item['kind']}' for {period_type} summary; allowed: {allowed_kinds}"
                )
            if not item["body"] or not str(item["body"]).strip():
                raise ValueError("item body must not be empty")
            item["body"] = str(item["body"]).strip()
        payload["items"] = raw_items

    # Validate topics
    if "topics" in payload:
        topics = payload["topics"]
        if topics is None:
            topics = []
        for t in topics:
            if t not in TOPIC_ENUM:
                raise ValueError(
                    f"Invalid topic '{t}'; must be one of the standard candidates"
                )
        if len(topics) > 5:
            raise ValueError("topics must contain at most 5 items")
        payload["topics"] = topics

    # Validate keywords: trim, drop empty, dedup
    if "keywords" in payload:
        kw = payload["keywords"]
        if kw is None:
            kw = []
        seen_kw = set()
        cleaned_kw = []
        for k in kw:
            trimmed = str(k).strip()
            if trimmed and trimmed not in seen_kw:
                seen_kw.add(trimmed)
                cleaned_kw.append(trimmed)
        payload["keywords"] = cleaned_kw

    # Validate people: dedup person_id, existence check
    if "people" in payload:
        people = payload["people"]
        if people is None:
            people = []
        seen_pids = set()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            for p in people:
                pid = p["person_id"]
                if pid in seen_pids:
                    raise ValueError(f"Duplicate person_id: {pid}")
                seen_pids.add(pid)
                cursor.execute(
                    "SELECT person_id FROM people WHERE person_id = ?", (pid,)
                )
                if cursor.fetchone() is None:
                    raise ValueError(f"Person not found: {pid}")
        finally:
            conn.close()
        payload["people"] = people

    # Validate mood/sleep_raw: day-only
    if ("mood" in payload or "sleep_raw" in payload) and period_type != "day":
        raise ValueError("mood and sleep_raw can only be set on day summaries")

    try:
        result = summary_store.update_summary(summary_id, payload)
    except ValueError:
        raise ValueError(f"Summary not found: {summary_id}")
    return result


def delete_summary_detail(summary_id: str) -> bool:
    return summary_store.delete_summary(summary_id)


# --- Task Config services ---

def get_task_config() -> dict:
    from obsidian_ai_hub.task_runner import (
        get_tasks_file_and_revision_locked,
        get_command_preset_info,
        compute_next_target,
    )
    filepath, sha, tasks = get_tasks_file_and_revision_locked()

    task_items = []
    now = datetime.now()

    for t in tasks:
        # Resolve preset info
        preset_info = get_command_preset_info(t.get("command", ""))

        # Calculate next execution explanation
        next_run_str = None
        try:
            next_run = compute_next_target(t.get("schedule", {}), now)
            next_run_str = next_run.isoformat()
        except Exception:
            pass

        task_items.append({
            "id": t.get("id"),
            "enabled": t.get("enabled", True),
            "schedule": t.get("schedule"),
            "command": t.get("command"),
            "is_preset": preset_info["is_preset"],
            "preset_flag": preset_info["flag"],
            "preset_name": preset_info["name"],
            "next_run": next_run_str,
        })

    return {
        "tasks": task_items,
        "filepath": str(filepath),
        "revision": sha,
    }


def update_task_config(revision: str, tasks: list) -> dict:
    from obsidian_ai_hub.task_runner import (
        acquire_task_config_lock,
        get_tasks_file_and_revision,
        validate_tasks,
        save_tasks_and_arm,
    )

    with acquire_task_config_lock():
        filepath, current_sha, old_tasks = get_tasks_file_and_revision()

        if revision != current_sha:
            raise TaskConfigConflictError()

        # Validate tasks
        validate_tasks(tasks)

        # Arm changed tasks and save atomically
        save_tasks_and_arm(tasks, old_tasks, datetime.now())

        # Reload to get the new sha
        _, new_sha, _ = get_tasks_file_and_revision()

    return {
        "success": True,
        "revision": new_sha,
    }


def preview_command(command: str) -> dict:
    from obsidian_ai_hub.task_runner import (
        parse_command,
        get_command_preset_info,
    )
    segments = parse_command(command)
    preset_info = get_command_preset_info(command)
    return {
        "segments": segments,
        "is_preset": preset_info["is_preset"],
        "preset_flag": preset_info["flag"],
        "preset_name": preset_info["name"],
    }
