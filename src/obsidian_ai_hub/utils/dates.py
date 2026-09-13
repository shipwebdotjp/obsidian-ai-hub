from __future__ import annotations

import calendar
import re
from typing import Optional

# Regex matching YYYY, YYYY-MM, YYYY-MM-DD, or slash/single-digit variations (e.g. YYYY/M/D, YYYY/M)
DATE_PRECISION_REGEX = re.compile(
    r"^(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?$"
)


def parse_and_normalize_partial_date(d_val: Optional[str]) -> Optional[str]:
    """Validate partial date string and return normalized ISO string (YYYY, YYYY-MM, or YYYY-MM-DD).

    Accepts YYYY, YYYY-MM, YYYY-MM-DD, and slash/single-digit variants (e.g. YYYY/M/D, YYYY/M).
    Raises ValueError if format or calendar values are invalid.
    Returns None if input is None or empty.
    """
    if d_val is None:
        return None
    s = str(d_val).strip()
    if not s:
        return None

    m = DATE_PRECISION_REGEX.match(s)
    if not m:
        raise ValueError(f"Invalid date format: {d_val}")

    year_str, month_str, day_str = m.groups()
    year = int(year_str)

    if month_str is None:
        return f"{year:04d}"

    month = int(month_str)
    if not (1 <= month <= 12):
        raise ValueError(f"Invalid month in date: {d_val}")

    if day_str is None:
        return f"{year:04d}-{month:02d}"

    day = int(day_str)
    last_day = calendar.monthrange(year, month)[1]
    if not (1 <= day <= last_day):
        raise ValueError(f"Invalid day in date: {d_val}")

    return f"{year:04d}-{month:02d}-{day:02d}"


def get_partial_date_bounds(d_val: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return (min_date, max_date) YYYY-MM-DD string bounds for a normalized or raw partial date string.

    Returns (None, None) if d_val is None or empty.
    Raises ValueError if d_val is invalid.
    """
    norm = parse_and_normalize_partial_date(d_val)
    if norm is None:
        return None, None

    parts = norm.split("-")
    if len(parts) == 1:
        y = int(parts[0])
        return f"{y:04d}-01-01", f"{y:04d}-12-31"
    elif len(parts) == 2:
        y, m = int(parts[0]), int(parts[1])
        last_day = calendar.monthrange(y, m)[1]
        return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last_day:02d}"
    else:
        return norm, norm
