import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from obsidian_ai_hub import memory
from obsidian_ai_hub.handler import obsidian_vault_retriever
from obsidian_ai_hub.web import schemas

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
    conn = memory.get_db_connection()
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


def review_memory(memory_id: str, action: str, new_content: Optional[str] = None) -> dict:
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
    switch_date: Optional[str] = None
) -> tuple[dict, Optional[dict]]:
    return memory.resolve_memory(
        candidate_id,
        action,
        target_memory_id,
        integrated_content=integrated_content,
        switch_date=switch_date
    )


def delete_memory(memory_id: str) -> dict:
    return memory.delete_memory(memory_id)


def batch_delete(memory_ids: list[str]) -> dict:
    return memory.batch_delete_memories(memory_ids)


def get_memory_options() -> dict:
    from obsidian_ai_hub.utils.topics import TOPIC_ENUM
    kinds_order = ["preference", "decision_policy", "fact", "commitment", "pattern", "episode"]
    kinds = [k for k in kinds_order if k in schemas.ALLOWED_KINDS]
    for k in sorted(list(schemas.ALLOWED_KINDS)):
        if k not in kinds_order:
            kinds.append(k)
    return {
        "kinds": kinds,
        "topics": list(TOPIC_ENUM)
    }


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


def review_research_theme(theme_id: str, action: str, reason: Optional[str] = None) -> Optional[dict]:
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

from datetime import datetime, date, timedelta
import calendar
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.activity import store as activity_store
from obsidian_ai_hub.utils.people_loader import load_people_notes_with_report
from obsidian_ai_hub.people_sync.sync import get_db_vault_conflicts_report

def parse_iso_datetime(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt

def get_day_activity_times(
    activity_logs: list[dict[str, Any]],
    target_date_str: str,
    now: Optional[datetime] = None
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

    is_today = (target_date == now.date())
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
    conn = memory.get_db_connection()
    latest_week_summary = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM summaries WHERE period_type = 'week' ORDER BY period_key DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            latest_week_summary = summary_store.get_summary_by_id(row["summary_id"], conn=conn)
    finally:
        conn.close()

    # Yesterday's summary
    yesterday_summary = summary_store.get_summary_by_period("day", yesterday_str)

    # Today's activity
    today_logs = activity_store.get_activities_by_date(today_str)
    mapped_logs = []
    for log in today_logs:
        mapped_logs.append({
            "activity_id": log.get("activity_id"),
            "occurred_at": log.get("occurred_at"),
            "app_name": log.get("app_name"),
            "window_title": log.get("window_title"),
            "summary": log.get("summary"),
            "category": log.get("category"),
            "keywords": log.get("keywords") or [],
        })

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
    conn = memory.get_db_connection()
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
        conn = memory.get_db_connection()
        months_summaries = []
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM summaries WHERE period_type = 'month' AND period_key LIKE ? ORDER BY period_key DESC",
                (f"{selected_year}-%",)
            )
            rows = cursor.fetchall()
            for r in rows:
                months_summaries.append(summary_store.get_summary_by_id(r["summary_id"], conn=conn))
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
        conn = memory.get_db_connection()
        days_data = {}
        try:
            cursor = conn.cursor()
            # Daily summaries in that month
            cursor.execute(
                "SELECT * FROM summaries WHERE period_type = 'day' AND period_key LIKE ? ORDER BY period_key DESC",
                (f"{month}-%",)
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
                (f"{month}-%",)
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

        return {
            "selectable_years": selectable_years,
            "selected_year": selected_year,
            "selected_month": month,
            "months": [],
            "weeks": overlapping_weeks,
            "days": sorted_days,
        }


def get_dashboard_day_details(target_date_str: str) -> dict:
    day_summary = summary_store.get_summary_by_period("day", target_date_str)

    logs = activity_store.get_activities_by_date(target_date_str)
    mapped_logs = []
    for log in logs:
        mapped_logs.append({
            "activity_id": log.get("activity_id"),
            "occurred_at": log.get("occurred_at"),
            "app_name": log.get("app_name"),
            "window_title": log.get("window_title"),
            "summary": log.get("summary"),
            "category": log.get("category"),
            "keywords": log.get("keywords") or [],
        })

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
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM summaries WHERE period_type = 'day' AND period_key >= ? AND period_key <= ? ORDER BY period_key ASC",
            (start_date_str, end_date_str)
        )
        rows = cursor.fetchall()
        for r in rows:
            all_day_summaries.append(summary_store.get_summary_by_id(r["summary_id"], conn=conn))
    finally:
        conn.close()

    topic_freq = {}
    keyword_freq = {}
    for s in all_day_summaries:
        for t in s.get("topics") or []:
            topic_freq[t] = topic_freq.get(t, 0) + 1
        for k in s.get("keywords") or []:
            keyword_freq[k] = keyword_freq.get(k, 0) + 1

    candidate_topics = [t for t, _ in sorted(topic_freq.items(), key=lambda x: x[1], reverse=True)[:20]]
    candidate_keywords = [k for k, _ in sorted(keyword_freq.items(), key=lambda x: x[1], reverse=True)[:20]]

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
        else: # month
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

    conn = memory.get_db_connection()
    logs_by_date = {}
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM activity_logs WHERE activity_date >= ? AND activity_date <= ? ORDER BY occurred_at ASC",
            (start_date_str, end_date_str)
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
        else: # month
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


# --- People Management services ---

def list_people() -> list[dict[str, Any]]:
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT person_id, display_name, normalized_name, vault_id FROM people")
        people_rows = [dict(r) for r in cursor.fetchall()]

        for p in people_rows:
            cursor.execute(
                "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
                (p["person_id"],)
            )
            p["aliases"] = [dict(r) for r in cursor.fetchall()]
        return people_rows
    finally:
        conn.close()


def get_person_detail(person_id: str) -> Optional[dict[str, Any]]:
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
            (person_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        p = dict(row)

        cursor.execute(
            "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ?",
            (p["person_id"],)
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
            (person_id,)
        )
        p["summaries"] = [dict(r) for r in cursor.fetchall()]
        return p
    finally:
        conn.close()


def list_person_candidates() -> list[dict[str, Any]]:
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT candidate_id, display_name, normalized_name, status FROM person_candidates")
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_person_candidate_detail(candidate_id: str) -> Optional[dict[str, Any]]:
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT candidate_id, display_name, normalized_name, status FROM person_candidates WHERE candidate_id = ?",
            (candidate_id,)
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
            (candidate_id,)
        )
        c["summaries"] = [dict(r) for r in cursor.fetchall()]
        return c
    finally:
        conn.close()


def resolve_person_candidate(candidate_id: str, target_person_id: str) -> dict[str, Any]:
    conn = memory.get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # 1. Fetch candidate
            cursor.execute(
                "SELECT candidate_id, display_name, normalized_name, status FROM person_candidates WHERE candidate_id = ?",
                (candidate_id,)
            )
            cand_row = cursor.fetchone()
            if cand_row is None:
                raise ValueError("Candidate not found")
            cand = dict(cand_row)

            # 2. Fetch target person
            cursor.execute(
                "SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE person_id = ?",
                (target_person_id,)
            )
            target_row = cursor.fetchone()
            if target_row is None:
                raise ValueError("Target person not found")
            target = dict(target_row)

            # Enforce target must be a Vault-linked person
            if not target.get("vault_id"):
                raise ValueError("未連携人物への解決は許可されていません。解決先はVault連携済みの人物だけに制限されています。")

            normalized_name = cand["normalized_name"]

            # 3. Conflict check 1: person_aliases
            cursor.execute(
                "SELECT person_id, display_name FROM person_aliases WHERE normalized_name = ?",
                (normalized_name,)
            )
            alias_row = cursor.fetchone()
            if alias_row is not None and alias_row["person_id"] != target_person_id:
                raise AliasConflictError(alias_row["person_id"], alias_row["display_name"])

            # 4. Conflict check 2: people.normalized_name
            cursor.execute(
                "SELECT person_id, display_name FROM people WHERE normalized_name = ?",
                (normalized_name,)
            )
            main_name_row = cursor.fetchone()
            if main_name_row is not None and main_name_row["person_id"] != target_person_id:
                raise MainNameConflictError(main_name_row["person_id"], main_name_row["display_name"])

            # 5. Insert alias
            conn.execute(
                "INSERT OR IGNORE INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
                (normalized_name, target_person_id, cand["display_name"])
            )

            # 6. Migrate summaries
            cursor.execute(
                "SELECT summary_id, note, display_order FROM summary_person_candidates WHERE candidate_id = ?",
                (candidate_id,)
            )
            links = cursor.fetchall()

            for link in links:
                summary_id = link["summary_id"]
                cand_note = link["note"]
                cand_order = link["display_order"]

                cursor.execute(
                    "SELECT note, display_order FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, target_person_id)
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
                        (merged_note, merged_order, summary_id, target_person_id)
                    )
                else:
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, target_person_id, cand_note, cand_order)
                    )

                conn.execute(
                    "DELETE FROM summary_person_candidates WHERE summary_id = ? AND candidate_id = ?",
                    (summary_id, candidate_id)
                )

            # 7. Delete candidate
            conn.execute("DELETE FROM person_candidates WHERE candidate_id = ?", (candidate_id,))

            return {"success": True}
    finally:
        conn.close()


def get_duplicate_candidates() -> dict[str, Any]:
    safe_map, report = load_people_notes_with_report()
    parsed_notes = report.get("parsed_notes", [])
    vault_notes_by_id = {n["id"]: n for n in parsed_notes}

    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()

        # Group 1: Unlinked people matching safe Vault input
        cursor.execute("SELECT person_id, display_name, normalized_name, vault_id FROM people WHERE vault_id IS NULL")
        unlinked_people = [dict(r) for r in cursor.fetchall()]

        vault_matches = []
        for p in unlinked_people:
            norm = p["normalized_name"]
            if norm in safe_map:
                v_note = safe_map[norm]
                vault_matches.append({
                    "unlinked_person": p,
                    "vault_person": {
                        "id": v_note["id"],
                        "name": v_note["name"],
                        "path": str(v_note["file_path"])
                    }
                })

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
                (v_id,)
            )
            members = [dict(r) for r in cursor.fetchall()]
            same_vault_id_groups.append({
                "vault_id": v_id,
                "people": members
            })

        return {
            "vault_matches": vault_matches,
            "same_vault_id_groups": same_vault_id_groups
        }
    finally:
        conn.close()


def merge_people(from_person_id: str, to_person_id: str) -> bool:
    conn = memory.get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # 1. Fetch people
            cursor.execute("SELECT person_id, display_name, vault_id FROM people WHERE person_id = ?", (from_person_id,))
            from_row = cursor.fetchone()
            if from_row is None:
                raise ValueError("Source person not found")
            from_p = dict(from_row)

            cursor.execute("SELECT person_id, display_name, vault_id FROM people WHERE person_id = ?", (to_person_id,))
            to_row = cursor.fetchone()
            if to_row is None:
                raise ValueError("Target person not found")
            to_p = dict(to_row)

            # Enforce target is a Vault-linked person
            if not to_p.get("vault_id"):
                raise ValueError("残す人物（統合先）はVault連携済みの人物である必要があります。")

            # Enforce from_p is either unlinked or has the exact same vault_id
            if from_p.get("vault_id") and from_p["vault_id"] != to_p["vault_id"]:
                raise ValueError("異なるVault IDを持つ人物同士の統合は拒否されます。")

            # 2. Migrate summary links
            cursor.execute("SELECT summary_id, note, display_order FROM summary_people WHERE person_id = ?", (from_person_id,))
            links = cursor.fetchall()

            for link in links:
                summary_id = link["summary_id"]
                note = link["note"]
                order = link["display_order"]

                cursor.execute(
                    "SELECT note, display_order FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, to_person_id)
                )
                existing_link = cursor.fetchone()

                if existing_link is not None:
                    notes_to_join = []
                    existing_note = existing_link["note"]
                    existing_order = existing_link["display_order"]

                    if existing_note and existing_note.strip():
                        notes_to_join.append(existing_note.strip())
                    if note and note.strip():
                        notes_to_join.append(note.strip())

                    merged_note = "\n".join(notes_to_join) if notes_to_join else None
                    merged_order = merge_display_orders(existing_order, order)

                    conn.execute(
                        "UPDATE summary_people SET note = ?, display_order = ? WHERE summary_id = ? AND person_id = ?",
                        (merged_note, merged_order, summary_id, to_person_id)
                    )
                else:
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, to_person_id, note, order)
                    )

                conn.execute(
                    "DELETE FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, from_person_id)
                )

            # 3. Migrate aliases
            # UPDATE OR IGNORE to move aliases
            conn.execute(
                "UPDATE OR IGNORE person_aliases SET person_id = ? WHERE person_id = ?",
                (to_person_id, from_person_id)
            )
            # Delete any aliases of from_person_id that couldn't be migrated due to unique key conflicts
            conn.execute("DELETE FROM person_aliases WHERE person_id = ?", (from_person_id,))

            # 4. Delete source person
            conn.execute("DELETE FROM people WHERE person_id = ?", (from_person_id,))

            return True
    finally:
        conn.close()


def sync_people() -> dict[str, Any]:
    people_notes_map, report = load_people_notes_with_report()
    parsed_notes = report.get("parsed_notes", [])

    conn = memory.get_db_connection()
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
                "normalized_name_collisions": report.get("normalized_name_collisions", []),
                "alias_collisions": report.get("alias_collisions", [])
            }
            return {
                "synced": True,
                "loader_report": clean_loader_report,
                "db_conflicts": db_conflicts
            }
    finally:
        conn.close()


def get_vault_report_dynamic() -> dict[str, Any]:
    people_notes_map, report = load_people_notes_with_report()
    parsed_notes = report.get("parsed_notes", [])

    conn = memory.get_db_connection()
    try:
        db_conflicts = get_db_vault_conflicts_report(conn, parsed_notes)
        clean_loader_report = {
            "file_deficiencies": report.get("file_deficiencies", []),
            "duplicate_ids": report.get("duplicate_ids", []),
            "normalized_name_collisions": report.get("normalized_name_collisions", []),
            "alias_collisions": report.get("alias_collisions", [])
        }
        return {
            "loader_report": clean_loader_report,
            "db_conflicts": db_conflicts
        }
    finally:
        conn.close()
