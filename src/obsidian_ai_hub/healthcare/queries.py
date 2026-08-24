"""Healthcare query helpers — on-the-fly aggregation over health_records.

No schema change; uses idx_hr_type_start (type, start_date) for the range scan.
Phase 1 covers Quantity types (value_numeric). Phase 2 adds Category types
(sleep/stand) where duration/count is derived from start_date/end_date/value_text.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any


def get_daily_aggregates(
    conn: sqlite3.Connection,
    *,
    type_: str,
    start_date: str,
    end_date: str,
) -> dict[str, dict[str, Any]]:
    """Return per-day aggregates for a single HealthKit type.

    Keys are YYYY-MM-DD strings for days that have at least one matching
    record (sparse). Days with no data are omitted. Callers are responsible
    for gap-filling if a continuous series is required.
    Each value is ``{"avg": float|None, "min":..., "max":..., "sum":..., "count": int}``.
    Only rows with ``value_numeric IS NOT NULL`` participate.

    The range filter uses ``start_date >= ? AND start_date < ?`` (next-day
    exclusive) so ``idx_hr_type_start(type, start_date)`` can serve the scan;
    grouping is by ``substr(start_date,1,10)`` to extract the date portion
    of the ISO string (e.g. ``"2026-08-20 08:00:00 +0900"`` → ``"2026-08-20"``).
    """
    # Validate type is non-empty to avoid full scan.
    if not type_:
        return {}

    # Validate dates quickly; caller already validated but be defensive.
    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
    except ValueError:
        return {}

    # Next-day exclusive upper bound for TEXT comparison trick.
    end_next = (e + timedelta(days=1)).isoformat()

    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            substr(start_date, 1, 10) AS day,
            AVG(value_numeric) AS avg_v,
            MIN(value_numeric) AS min_v,
            MAX(value_numeric) AS max_v,
            SUM(value_numeric) AS sum_v,
            COUNT(*) AS cnt
        FROM health_records
        WHERE type = ?
          AND start_date >= ?
          AND start_date < ?
          AND value_numeric IS NOT NULL
        GROUP BY day
        ORDER BY day ASC
        """,
        (type_, start_date, end_next),
    )
    result: dict[str, dict[str, Any]] = {}
    for row in cur.fetchall():
        # Use tuple indexing to avoid dependency on conn.row_factory = sqlite3.Row.
        day = row[0]
        avg_v = row[1]
        min_v = row[2]
        max_v = row[3]
        sum_v = row[4]
        cnt = row[5]
        result[day] = {
            "avg": avg_v,
            "min": min_v,
            "max": max_v,
            "sum": sum_v,
            "count": int(cnt),
        }
    return result


def get_daily_aggregates_multi(
    conn: sqlite3.Connection,
    *,
    types: list[str],
    start_date: str,
    end_date: str,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Batch version of :func:`get_daily_aggregates` for multiple types.

    Returns ``{type: {day: {avg, min, max, sum, count}}}`` using a single
    grouped query. Sparse: days with no data are omitted.
    """
    if not types:
        return {}
    # Validate dates defensively
    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
    except ValueError:
        return {t: {} for t in types}
    end_next = (e + timedelta(days=1)).isoformat()
    # Filter to unique non-empty types to avoid duplicate placeholders.
    uniq = [t for t in dict.fromkeys(types) if t]
    if not uniq:
        return {}
    placeholders = ",".join("?" for _ in uniq)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            type AS t,
            substr(start_date, 1, 10) AS day,
            AVG(value_numeric) AS avg_v,
            MIN(value_numeric) AS min_v,
            MAX(value_numeric) AS max_v,
            SUM(value_numeric) AS sum_v,
            COUNT(*) AS cnt
        FROM health_records
        WHERE type IN ({placeholders})
          AND start_date >= ?
          AND start_date < ?
          AND value_numeric IS NOT NULL
        GROUP BY t, day
        ORDER BY t ASC, day ASC
        """,
        (*uniq, start_date, end_next),
    )
    out: dict[str, dict[str, dict[str, Any]]] = {t: {} for t in uniq}
    for row in cur.fetchall():
        t = row[0]
        day = row[1]
        avg_v = row[2]
        min_v = row[3]
        max_v = row[4]
        sum_v = row[5]
        cnt = row[6]
        out[t][day] = {
            "avg": avg_v,
            "min": min_v,
            "max": max_v,
            "sum": sum_v,
            "count": int(cnt),
        }
    return out


def _parse_health_datetime(s: str) -> datetime | None:
    """Parse Apple Health start/end strings like ``2026-08-20 23:00:00 +0900``.

    Returns None on failure; caller skips the row rather than masking.
    """
    if not s or not isinstance(s, str):
        return None
    # Primary format from export.xml
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # Fallback: ISO with T separator or without timezone
    try:
        # fromisoformat handles "YYYY-MM-DD HH:MM:SS+09:00" if colon in tz
        # but export uses "+0900" without colon; try inserting colon.
        if len(s) >= 5 and s[-5] in ("+", "-") and s[-2:].isdigit():
            # already with colon? fromisoformat tolerates
            return datetime.fromisoformat(s)
    except ValueError:
        pass
    try:
        # Normalize "+0900" -> "+09:00" for fromisoformat
        if len(s) > 6 and s[-5] in ("+", "-") and s[-4:].isdigit():
            s2 = s[:-2] + ":" + s[-2:]
            return datetime.fromisoformat(s2)
    except ValueError:
        pass
    return None


def get_daily_category_durations(
    conn: sqlite3.Connection,
    *,
    type_: str,
    start_date: str,
    end_date: str,
    allowed_values: set[str] | None = None,
) -> dict[str, float]:
    """Return per-day total duration (hours) for a Category type.

    Groups by ``substr(start_date,1,10)`` (the start day). Only rows whose
    ``value_text`` is in ``allowed_values`` (if given) contribute. Duration
    is ``(end-start).total_seconds()/3600`` with timezone-aware parsing.
    Sparse: days with no matching rows are omitted.
    """
    if not type_:
        return {}
    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
    except ValueError:
        return {}
    end_next = (e + timedelta(days=1)).isoformat()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            substr(start_date, 1, 10) AS day,
            start_date,
            end_date,
            value_text
        FROM health_records
        WHERE type = ?
          AND start_date >= ?
          AND start_date < ?
        ORDER BY day ASC
        """,
        (type_, start_date, end_next),
    )
    out: dict[str, float] = {}
    for row in cur.fetchall():
        day = row[0]
        start_s = row[1]
        end_s = row[2]
        vtext = row[3]
        if allowed_values is not None and vtext not in allowed_values:
            continue
        start_dt = _parse_health_datetime(start_s)
        end_dt = _parse_health_datetime(end_s)
        if start_dt is None or end_dt is None:
            continue
        # Ensure timezone awareness doesn't break subtraction; both have same tz
        # if present, otherwise naive subtraction is fine.
        try:
            delta = (end_dt - start_dt).total_seconds()
        except Exception:
            continue
        if delta <= 0 or delta > 24 * 3600 * 2:  # guard against bogus >2 days
            # Skip zero/negative or implausibly long segments; do not mask
            # other rows. 24*2 allows overnight sleep plus InBed.
            if delta <= 0:
                continue
            # For unusually long InBed (e.g., 12h) it's still <24, so allow up to 24h.
            # Only skip >48h as likely data error.
            if delta > 48 * 3600:
                continue
        hours = delta / 3600.0
        out[day] = out.get(day, 0.0) + hours
    return out


def get_daily_stand_counts(
    conn: sqlite3.Connection,
    *,
    start_date: str,
    end_date: str,
) -> dict[str, int]:
    """Return per-day count of stood hours for AppleStandHour.

    Counts rows where ``value_text == 'HKCategoryValueAppleStandHourStood'``.
    Grouped by start day, sparse.
    """
    if not start_date or not end_date:
        return {}
    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
    except ValueError:
        return {}
    end_next = (e + timedelta(days=1)).isoformat()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            substr(start_date, 1, 10) AS day,
            COUNT(*) AS cnt
        FROM health_records
        WHERE type = 'HKCategoryTypeIdentifierAppleStandHour'
          AND value_text = 'HKCategoryValueAppleStandHourStood'
          AND start_date >= ?
          AND start_date < ?
        GROUP BY day
        ORDER BY day ASC
        """,
        (start_date, end_next),
    )
    out: dict[str, int] = {}
    for row in cur.fetchall():
        day = row[0]
        cnt = row[1]
        out[day] = int(cnt)
    return out


def list_available_types(
    conn: sqlite3.Connection,
    *,
    limit: int = 100,
) -> list[str]:
    """List distinct health_records.type values."""
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT type FROM health_records ORDER BY type ASC LIMIT ?", (limit,))
    return [r[0] for r in cur.fetchall()]
