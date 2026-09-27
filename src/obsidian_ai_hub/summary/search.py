"""Read model for summary search (summary_search).

Provides hierarchical range selection, filter evaluation, coverage calculation,
and output budget trimming across daily, weekly, and monthly summaries stored in SQLite.
"""

import json
import logging
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.summary.store import _attach_children_bulk, deserialize_summary

logger = logging.getLogger(__name__)

BUDGET_LIMIT_CHARS = 5500
MAX_RANGES_COUNT = 20


def normalize_text(text: str) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFKC", str(text)).casefold()


def parse_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def format_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def compute_max_granularity(start_d: date, end_d: date, granularity: str) -> str:
    if granularity in ("day", "week", "month"):
        return granularity
    if granularity != "auto":
        raise ValueError(f"Invalid granularity: {granularity}")
    total_days = (end_d - start_d).days + 1
    if total_days <= 31:
        return "day"
    elif total_days <= 180:
        return "week"
    else:
        return "month"


def match_entry(
    entry: Dict[str, Any],
    query: Optional[str],
    topics: Optional[List[str]],
    project_ids: Optional[List[int]],
    person_ids: Optional[List[str]],
) -> Tuple[bool, List[str]]:
    matched_fields_q: List[str] = []
    matched_fields_filter: List[str] = []

    # 1. Query filter
    if query is not None and query.strip():
        norm_q = normalize_text(query)
        q_matched = False

        # summary
        if entry.get("summary") and norm_q in normalize_text(entry["summary"]):
            matched_fields_q.append("summary")
            q_matched = True

        # keywords
        for kw in entry.get("keywords") or []:
            if norm_q in normalize_text(kw):
                if "keywords" not in matched_fields_q:
                    matched_fields_q.append("keywords")
                q_matched = True

        # items
        for item in entry.get("items") or []:
            body = item.get("body", "") if isinstance(item, dict) else ""
            if norm_q in normalize_text(body):
                if "items" not in matched_fields_q:
                    matched_fields_q.append("items")
                q_matched = True

        # projects (display_name & notes)
        for proj in entry.get("project_notes") or []:
            name = proj.get("display_name", "")
            note = proj.get("note", "")
            if norm_q in normalize_text(name) or norm_q in normalize_text(note):
                if "projects" not in matched_fields_q:
                    matched_fields_q.append("projects")
                q_matched = True
        if "projects" not in matched_fields_q:
            for p_name in entry.get("projects") or []:
                if norm_q in normalize_text(p_name):
                    matched_fields_q.append("projects")
                    q_matched = True
                    break

        # people (name & notes)
        for person in entry.get("people") or []:
            p_name = person.get("name", "") if isinstance(person, dict) else ""
            p_note = person.get("note", "") if isinstance(person, dict) else ""
            if norm_q in normalize_text(p_name) or norm_q in normalize_text(p_note):
                if "people" not in matched_fields_q:
                    matched_fields_q.append("people")
                q_matched = True

        if not q_matched:
            return False, []

    # 2. Topics filter (OR within topics)
    if topics:
        norm_topics = {normalize_text(t) for t in topics if t}
        entry_topics = {normalize_text(t) for t in (entry.get("topics") or [])}
        if norm_topics & entry_topics:
            matched_fields_filter.append("topics")
        else:
            return False, []

    # 3. Project IDs filter (OR within project_ids)
    if project_ids:
        wanted_pids = set(project_ids)
        entry_pids = set(entry.get("project_ids") or [])
        if wanted_pids & entry_pids:
            matched_fields_filter.append("projects")
        else:
            return False, []

    # 4. Person IDs filter (OR within person_ids)
    if person_ids:
        wanted_pids = set(person_ids)
        entry_pids = set()
        for p in entry.get("people") or []:
            if isinstance(p, dict) and p.get("person_id"):
                entry_pids.add(p["person_id"])
        if wanted_pids & entry_pids:
            matched_fields_filter.append("people")
        else:
            return False, []

    # Combine unique matched fields preserving order
    combined: List[str] = []
    for f in matched_fields_q + matched_fields_filter:
        if f not in combined:
            combined.append(f)

    return True, combined


def _merge_dates_to_ranges(dates: Set[date]) -> Tuple[List[Dict[str, str]], bool]:
    if not dates:
        return [], False

    sorted_dates = sorted(dates)
    ranges: List[Tuple[date, date]] = []
    cur_start = sorted_dates[0]
    cur_end = sorted_dates[0]

    for d in sorted_dates[1:]:
        if d == cur_end + timedelta(days=1):
            cur_end = d
        else:
            ranges.append((cur_start, cur_end))
            cur_start = d
            cur_end = d
    ranges.append((cur_start, cur_end))

    # Sort ranges DESC (newest first)
    ranges.sort(key=lambda r: r[0], reverse=True)

    is_truncated = len(ranges) > MAX_RANGES_COUNT
    capped = ranges[:MAX_RANGES_COUNT]

    formatted = [
        {"start_date": format_date(r[0]), "end_date": format_date(r[1])}
        for r in capped
    ]
    return formatted, is_truncated


def _sanitize_entry_for_output(
    entry: Dict[str, Any], matched_fields: List[str]
) -> Dict[str, Any]:
    p_start = entry.get("period_start") or entry.get("period_key")
    p_end = entry.get("period_end") or entry.get("period_key")
    out = {
        "period_type": entry.get("period_type"),
        "period_key": entry.get("period_key"),
        "period_start": p_start,
        "period_end": p_end,
        "summary_id": entry.get("summary_id"),
        "summary": entry.get("summary") or "",
        "keywords": entry.get("keywords") or [],
        "topics": entry.get("topics") or [],
        "items": [
            {"kind": i.get("kind"), "body": i.get("body")}
            for i in (entry.get("items") or [])
            if isinstance(i, dict)
        ],
        "project_ids": entry.get("project_ids") or [],
        "projects": entry.get("projects") or [],
        "people": [
            {
                "person_id": p.get("person_id"),
                "name": p.get("name"),
                "note": p.get("note"),
            }
            for p in (entry.get("people") or [])
            if isinstance(p, dict)
        ],
        "matched_fields": matched_fields,
        "entry_truncated": False,
    }
    if entry.get("period_type") == "day":
        out["mood"] = entry.get("mood")
        out["sleep_hours"] = entry.get("sleep_hours")

    return out


def _truncate_entry_body(entry: Dict[str, Any], target_limit: int) -> bool:
    """Attempt to truncate entry content (items body / summary) to reduce JSON size."""
    items = entry.get("items") or []
    truncated_any = False
    for item in items:
        body = item.get("body", "")
        if len(body) > 100:
            item["body"] = body[:100] + "..."
            truncated_any = True

    summary = entry.get("summary", "")
    if len(summary) > 300:
        entry["summary"] = summary[:300] + "..."
        truncated_any = True

    if truncated_any:
        entry["entry_truncated"] = True
    return truncated_any


def search_summaries(
    start_date: str,
    end_date: str,
    query: Optional[str] = None,
    topics: Optional[List[str]] = None,
    project_ids: Optional[List[int]] = None,
    person_ids: Optional[List[str]] = None,
    granularity: str = "auto",
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    # Validate dates
    try:
        start_d = parse_date(start_date)
        end_d = parse_date(end_date)
    except Exception as exc:
        raise ValueError(f"Invalid date format: {exc}") from exc

    if start_d > end_d:
        raise ValueError(f"start_date ({start_date}) cannot be after end_date ({end_date})")

    max_gran = compute_max_granularity(start_d, end_d, granularity)

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()

        # Load all summaries in range to inspect DB availability and candidates
        # 1. Month summaries
        cursor.execute(
            "SELECT * FROM summaries WHERE period_type = 'month' AND period_end >= ? AND period_start <= ?",
            (start_date, end_date),
        )
        month_rows = [deserialize_summary(r) for r in cursor.fetchall()]
        _attach_children_bulk(conn, month_rows)

        # 2. Week summaries
        cursor.execute(
            "SELECT * FROM summaries WHERE period_type = 'week' AND period_end >= ? AND period_start <= ?",
            (start_date, end_date),
        )
        week_rows = [deserialize_summary(r) for r in cursor.fetchall()]
        _attach_children_bulk(conn, week_rows)

        # 3. Day summaries
        cursor.execute(
            "SELECT * FROM summaries WHERE period_type = 'day' AND period_key >= ? AND period_key <= ?",
            (start_date, end_date),
        )
        day_rows = [deserialize_summary(r) for r in cursor.fetchall()]
        _attach_children_bulk(conn, day_rows)

        # Build day-by-day map of DB availability
        total_days = (end_d - start_d).days + 1
        all_requested_dates = [start_d + timedelta(days=i) for i in range(total_days)]

        source_covered_dates: Set[date] = set()
        source_missing_dates: Set[date] = set()

        for d in all_requested_dates:
            d_str = format_date(d)
            has_month = any(
                m["period_start"] <= d_str <= m["period_end"] for m in month_rows
            )
            has_week = any(
                w["period_start"] <= d_str <= w["period_end"] for w in week_rows
            )
            has_day = any(dy["period_key"] == d_str for dy in day_rows)

            if has_month or has_week or has_day:
                source_covered_dates.add(d)
            else:
                source_missing_dates.add(d)

        # Hierarchical selection of candidates
        uncovered_dates: Set[date] = set(all_requested_dates)
        candidate_entries: List[Dict[str, Any]] = []
        covered_matched_dates: Set[date] = set()

        # Step 1: Month candidates if max_gran == 'month'
        if max_gran == "month":
            # Sort month_rows by period_start DESC
            month_rows.sort(key=lambda m: m["period_start"], reverse=True)
            for m in month_rows:
                m_start = parse_date(m["period_start"])
                m_end = parse_date(m["period_end"])
                # Must fit completely in [start_d, end_d]
                if m_start >= start_d and m_end <= end_d:
                    m_days = {
                        m_start + timedelta(days=i)
                        for i in range((m_end - m_start).days + 1)
                    }
                    if m_days.issubset(uncovered_dates):
                        is_match, fields = match_entry(
                            m, query, topics, project_ids, person_ids
                        )
                        if is_match:
                            candidate_entries.append(
                                _sanitize_entry_for_output(m, fields)
                            )
                            uncovered_dates -= m_days
                            covered_matched_dates.update(m_days)

        # Step 2: Week candidates if max_gran in ('month', 'week')
        if max_gran in ("month", "week"):
            week_rows.sort(key=lambda w: w["period_start"], reverse=True)
            for w in week_rows:
                w_start = parse_date(w["period_start"])
                w_end = parse_date(w["period_end"])
                if w_start >= start_d and w_end <= end_d:
                    w_days = {
                        w_start + timedelta(days=i)
                        for i in range((w_end - w_start).days + 1)
                    }
                    if w_days.issubset(uncovered_dates):
                        is_match, fields = match_entry(
                            w, query, topics, project_ids, person_ids
                        )
                        if is_match:
                            candidate_entries.append(
                                _sanitize_entry_for_output(w, fields)
                            )
                            uncovered_dates -= w_days
                            covered_matched_dates.update(w_days)

        # Step 3: Day candidates for remaining uncovered dates
        for dy in day_rows:
            if not dy.get("period_start"):
                dy["period_start"] = dy.get("period_key")
            if not dy.get("period_end"):
                dy["period_end"] = dy.get("period_key")

        day_rows.sort(key=lambda dy: dy["period_key"], reverse=True)
        for dy in day_rows:
            dy_date = parse_date(dy["period_key"])
            if dy_date in uncovered_dates:
                is_match, fields = match_entry(
                    dy, query, topics, project_ids, person_ids
                )
                if is_match:
                    candidate_entries.append(
                        _sanitize_entry_for_output(dy, fields)
                    )
                    uncovered_dates.remove(dy_date)
                    covered_matched_dates.add(dy_date)

        # Sort candidate entries DESC by period_start
        candidate_entries.sort(key=lambda e: e["period_start"], reverse=True)

        # Calculate filter matching sets
        has_filters = bool((query and query.strip()) or topics or project_ids or person_ids)
        if not has_filters:
            filter_matched_dates = set(source_covered_dates)
            filter_unmatched_dates = set()
        else:
            filter_matched_dates = set(covered_matched_dates)
            filter_unmatched_dates = source_covered_dates - filter_matched_dates

        # Precompute missing and unmatched ranges for budget estimation
        sample_missing_ranges, sample_missing_tr = _merge_dates_to_ranges(source_missing_dates)
        sample_unmatched_ranges, sample_unmatched_tr = _merge_dates_to_ranges(filter_unmatched_dates)

        # Truncation and Budget allocation
        returned_entries: List[Dict[str, Any]] = []
        returned_dates: Set[date] = set()
        any_entry_body_truncated = False
        period_units_truncated = False
        last_returned_period_start: Optional[str] = None

        def estimate_response_size(current_entries: List[Dict[str, Any]]) -> int:
            cur_dates: Set[date] = set()
            for e in current_entries:
                e_s = parse_date(e["period_start"])
                e_e = parse_date(e["period_end"])
                for i in range((e_e - e_s).days + 1):
                    cur_dates.add(e_s + timedelta(days=i))
            cur_ranges, cur_tr = _merge_dates_to_ranges(cur_dates)

            sample_payload = {
                "requested_range": {"start_date": start_date, "end_date": end_date},
                "granularity": max_gran,
                "entries": current_entries,
                "coverage": {
                    "requested_days": total_days,
                    "source_covered_days": len(source_covered_dates),
                    "source_missing_days": len(source_missing_dates),
                    "filter_matched_days": len(filter_matched_dates),
                    "filter_unmatched_days": len(filter_unmatched_dates),
                    "returned_days": len(cur_dates),
                    "source_missing_ranges": sample_missing_ranges,
                    "filter_unmatched_ranges": sample_unmatched_ranges,
                    "returned_ranges": cur_ranges,
                    "ranges_truncated": {
                        "source_missing": sample_missing_tr,
                        "filter_unmatched": sample_unmatched_tr,
                        "returned": cur_tr,
                    },
                },
                "truncated": False,
                "next_request": None,
            }
            return len(json.dumps(sample_payload, ensure_ascii=False))

        for idx, entry in enumerate(candidate_entries):
            # Try adding entry as-is
            test_entries = returned_entries + [entry]
            size = estimate_response_size(test_entries)

            if size <= BUDGET_LIMIT_CHARS:
                returned_entries.append(entry)
                e_start = parse_date(entry["period_start"])
                e_end = parse_date(entry["period_end"])
                for i in range((e_end - e_start).days + 1):
                    returned_dates.add(e_start + timedelta(days=i))
                last_returned_period_start = entry["period_start"]
            else:
                # Try truncating entry body
                truncated_body = _truncate_entry_body(entry, BUDGET_LIMIT_CHARS)
                if truncated_body:
                    size = estimate_response_size(returned_entries + [entry])
                    if size <= BUDGET_LIMIT_CHARS:
                        returned_entries.append(entry)
                        any_entry_body_truncated = True
                        e_start = parse_date(entry["period_start"])
                        e_end = parse_date(entry["period_end"])
                        for i in range((e_end - e_start).days + 1):
                            returned_dates.add(e_start + timedelta(days=i))
                        last_returned_period_start = entry["period_start"]
                        # Stop adding further entries since budget is tight
                        if idx < len(candidate_entries) - 1:
                            period_units_truncated = True
                        break

                period_units_truncated = True
                break

        top_level_truncated = period_units_truncated or any_entry_body_truncated

        # Build next_request if period units were truncated
        next_request: Optional[Dict[str, Any]] = None
        if period_units_truncated and last_returned_period_start:
            oldest_returned_dt = parse_date(last_returned_period_start)
            next_end_dt = oldest_returned_dt - timedelta(days=1)
            if next_end_dt >= start_d:
                next_request = {
                    "start_date": start_date,
                    "end_date": format_date(next_end_dt),
                    "query": query,
                    "topics": topics,
                    "project_ids": project_ids,
                    "person_ids": person_ids,
                    "granularity": granularity,
                }

        # Build ranges for coverage
        missing_ranges, missing_tr = _merge_dates_to_ranges(source_missing_dates)
        unmatched_ranges, unmatched_tr = _merge_dates_to_ranges(
            filter_unmatched_dates
        )
        returned_ranges, returned_tr = _merge_dates_to_ranges(returned_dates)

        coverage = {
            "requested_days": total_days,
            "source_covered_days": len(source_covered_dates),
            "source_missing_days": len(source_missing_dates),
            "filter_matched_days": len(filter_matched_dates),
            "filter_unmatched_days": len(filter_unmatched_dates),
            "returned_days": len(returned_dates),
            "source_missing_ranges": missing_ranges,
            "filter_unmatched_ranges": unmatched_ranges,
            "returned_ranges": returned_ranges,
            "ranges_truncated": {
                "source_missing": missing_tr,
                "filter_unmatched": unmatched_tr,
                "returned": returned_tr,
            },
        }

        return {
            "requested_range": {"start_date": start_date, "end_date": end_date},
            "granularity": max_gran,
            "entries": returned_entries,
            "coverage": coverage,
            "truncated": top_level_truncated,
            "next_request": next_request,
        }
    finally:
        if close_conn:
            conn.close()
