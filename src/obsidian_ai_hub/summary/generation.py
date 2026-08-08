"""Shared, synchronous summary generation entry point for CLI and web callers."""

from datetime import datetime

from obsidian_ai_hub.summary import store as summary_store


class SummaryGenerationError(ValueError):
    """The model did not produce a usable summary."""


def generate_summary(period_type: str, *, target_date: str | None = None, target_month: str | None = None) -> dict:
    """Generate and persist one summary, returning its fully loaded detail record."""
    if period_type == "day":
        from obsidian_ai_hub.summerize_day import summarize_day
        result = summarize_day(datetime.strptime(target_date or "", "%Y-%m-%d"))
        key = target_date
    elif period_type == "week":
        from obsidian_ai_hub.summerize_week import summarize_week
        result = summarize_week(datetime.strptime(target_date or "", "%Y-%m-%d"))
        target = datetime.strptime(target_date or "", "%Y-%m-%d")
        iso_year, iso_week, _ = target.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
    elif period_type == "month":
        from obsidian_ai_hub.summerize_month import summarize_month
        result = summarize_month(datetime.strptime(target_month or "", "%Y-%m"))
        key = target_month
    else:
        raise ValueError("Invalid period_type")

    if not result or not result.get("summary"):
        raise SummaryGenerationError("Generated summary is empty")
    detail = summary_store.get_summary_by_period(period_type, key or "")
    if detail is None:
        raise RuntimeError("Generated summary was not persisted")
    return detail
