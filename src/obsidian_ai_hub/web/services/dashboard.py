import calendar
from datetime import datetime, timedelta
from typing import Any, Optional

from obsidian_ai_hub.activity import store as activity_store
from obsidian_ai_hub.activity.categories import ACTIVITY_CATEGORIES
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.summary import store as summary_store


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
                "project_id": log.get("project_id"),
                "project_name": log.get("project_name"),
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
                "project_id": log.get("project_id"),
                "project_name": log.get("project_name"),
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

    hourly_category_buckets = []
    for hour in range(24):
        hourly_category_buckets.append({
            "hour": hour,
            "total_log_count": 0,
            "category_counts": {},
        })

    all_logs_in_range = [
        log for day_logs in logs_by_date.values() for log in day_logs
    ]
    for log in all_logs_in_range:
        occurred_at = log.get("occurred_at")
        if not occurred_at:
            continue
        try:
            log_dt = datetime.fromisoformat(occurred_at)
        except (ValueError, TypeError):
            continue
        hour = log_dt.hour
        category = log.get("category")
        if not category:
            category = "その他"

        bucket = hourly_category_buckets[hour]
        bucket["total_log_count"] += 1
        bucket["category_counts"][category] = (
            bucket["category_counts"].get(category, 0) + 1
        )

    activity_categories = list(ACTIVITY_CATEGORIES)
    for bucket in hourly_category_buckets:
        for cat in bucket["category_counts"]:
            if cat not in activity_categories:
                activity_categories.append(cat)

    return {
        "granularity": granularity,
        "buckets": sorted_buckets,
        "candidate_topics": candidate_topics,
        "candidate_keywords": candidate_keywords,
        "activity_categories": activity_categories,
        "hourly_category_buckets": hourly_category_buckets,
    }
