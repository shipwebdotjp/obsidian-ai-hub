"""Healthcare query helpers — on-the-fly aggregation over health_records.

No schema change; uses idx_hr_type_start (type, start_date) for the range scan.
Phase 1 covers Quantity types (value_numeric). Category types (sleep/stand) are
deferred to Phase 2 where duration computation is needed.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
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


def list_available_types(
    conn: sqlite3.Connection,
    *,
    limit: int = 100,
) -> list[str]:
    """List distinct health_records.type values."""
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT type FROM health_records ORDER BY type ASC LIMIT ?", (limit,))
    return [r[0] for r in cur.fetchall()]
