"""Expand the regularly_*_events config rules across a display range.

The config file (config.yml: regularly_weekday_events / regularly_date_events)
is the single source of truth for recurring events. Rules are expanded
computationally for the requested range; recurring items are read-only and can
never be edited, rejected, or promoted to Apple.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, List

from obsidian_ai_hub.utils import config

CAT_TASK = 1
CAT_EVENT = 2
WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"]


def get_weekday_rule_dates(
    target_date: date, weekdays: List[int], nth: List[int]
) -> List[date]:
    """Return dates within the month of target_date that match weekday numbers
    and nth occurrences (0=Sunday..6=Saturday, nth 1-based).
    """
    year = target_date.year
    month = target_date.month
    results: List[date] = []

    for weekday in weekdays:
        days_in_month: List[date] = []
        for d in range(1, 32):
            try:
                dt = date(year, month, d)
            except ValueError:
                break
            if dt.weekday() == (weekday - 1 if weekday != 0 else 6):
                days_in_month.append(dt)

        for idx, dd in enumerate(days_in_month, start=1):
            if idx in nth:
                results.append(dd)

    return results


def get_monthday_rule_dates(target_day: date, dates: List[int]) -> List[date]:
    """Return concrete date objects in the same year/month as target_day for the
    provided day numbers (0 = last day of month). Invalid dates are skipped.
    """
    results: List[date] = []
    year = target_day.year
    month = target_day.month
    for d in dates:
        if d == 0:
            if month == 12:
                next_month_first = date(year + 1, 1, 1)
            else:
                next_month_first = date(year, month + 1, 1)
            results.append(next_month_first - timedelta(days=1))
            continue
        try:
            results.append(date(year, month, d))
        except ValueError:
            pass
    return results


def is_date_in_list(target: date, days: List[date]) -> bool:
    return any(
        d.year == target.year and d.month == target.month and d.day == target.day
        for d in days
    )


def _matches_weekday_rule(target_day: date, rule: list) -> bool:
    nth = rule[0]
    days_string = rule[1]
    day_offset = rule[2]
    days_number = [WEEKDAYS.index(w) for w in days_string]
    target = target_day - timedelta(days=day_offset)
    target_dates = get_weekday_rule_dates(target, days_number, nth)
    return is_date_in_list(target, target_dates)


def _matches_date_rule(target_day: date, rule: list) -> bool:
    day_numbers = rule[0]
    day_offset = rule[1]
    target = target_day - timedelta(days=day_offset)
    target_dates = get_monthday_rule_dates(target, day_numbers)
    return is_date_in_list(target, target_dates)


def expand_recurring(start_date: date, end_date: date) -> list[dict]:
    """Expand recurring config rules into concrete items for [start, end].

    Each returned dict has: title, date (date object), category (CAT_TASK /
    CAT_EVENT), kind ('task' | 'event'), and source='recurring'.
    """
    if start_date > end_date:
        return []

    items: list[dict] = []

    weekday_rules: list[Any] = list(config.REGULARLY_WEEKDAY_EVENTS or [])
    date_rules: list[Any] = list(config.REGULARLY_DATE_EVENTS or [])

    current = start_date
    while current <= end_date:
        for rule in weekday_rules:
            try:
                event_name = rule[3]
                category = rule[4]
            except (IndexError, TypeError):
                continue
            if _matches_weekday_rule(current, rule):
                items.append(
                    {
                        "title": event_name,
                        "date": current,
                        "category": category,
                        "kind": "task" if category == CAT_TASK else "event",
                        "source": "recurring",
                    }
                )

        for rule in date_rules:
            try:
                event_name = rule[2]
                category = rule[3]
            except (IndexError, TypeError):
                continue
            if _matches_date_rule(current, rule):
                items.append(
                    {
                        "title": event_name,
                        "date": current,
                        "category": category,
                        "kind": "task" if category == CAT_TASK else "event",
                        "source": "recurring",
                    }
                )

        current += timedelta(days=1)

    return items