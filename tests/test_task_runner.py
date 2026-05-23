from datetime import datetime
import pytest

from obsidian_ai_hub.task_runner import compute_target


def test_minutely_default_second_returns_now():
    now = datetime(2026, 1, 29, 10, 15, 30)
    schedule = {"type": "minutely"}
    # should return 10:15:00
    expected = datetime(2026, 1, 29, 10, 15, 0)
    assert compute_target(schedule, now) == expected


def test_minutely_specific_second_past():
    now = datetime(2026, 1, 29, 10, 15, 30)
    schedule = {"type": "minutely", "second": 15}
    # should return 10:15:15
    expected = datetime(2026, 1, 29, 10, 15, 15)
    assert compute_target(schedule, now) == expected


def test_minutely_specific_second_future_returns_previous_minute():
    now = datetime(2026, 1, 29, 10, 15, 30)
    schedule = {"type": "minutely", "second": 45}
    # should return 10:14:45
    expected = datetime(2026, 1, 29, 10, 14, 45)
    assert compute_target(schedule, now) == expected


def test_hourly_future_minute_returns_previous_hour():
    now = datetime(2026, 1, 29, 10, 15)
    schedule = {"type": "hourly", "minute": 30}
    expected = datetime(2026, 1, 29, 9, 30)
    assert compute_target(schedule, now) == expected


def test_hourly_exact_minute_returns_now():
    now = datetime(2026, 1, 29, 10, 15)
    schedule = {"type": "hourly", "minute": 15}
    expected = datetime(2026, 1, 29, 10, 15)
    assert compute_target(schedule, now) == expected


def test_daily_past_time_same_day():
    now = datetime(2026, 1, 29, 10, 0)
    schedule = {"type": "daily", "hour": 9, "minute": 30}
    expected = datetime(2026, 1, 29, 9, 30)
    assert compute_target(schedule, now) == expected


def test_daily_future_time_previous_day():
    now = datetime(2026, 1, 29, 10, 0)
    schedule = {"type": "daily", "hour": 12, "minute": 0}
    expected = datetime(2026, 1, 28, 12, 0)
    assert compute_target(schedule, now) == expected


def test_weekly_previous_weekday():
    # 2021-08-10 is a Tuesday (weekday=1)
    now = datetime(2021, 8, 10, 10, 0)
    # ask for Monday (weekday=0)
    schedule = {"type": "weekly", "weekday": 0, "hour": 9, "minute": 0}
    expected = datetime(2021, 8, 9, 9, 0)
    assert compute_target(schedule, now) == expected


def test_weekly_same_weekday_but_time_in_future_goes_previous_week():
    # 2021-08-10 is a Tuesday (weekday=1)
    now = datetime(2021, 8, 10, 10, 0)
    # Tuesday at 12:00 is later today, so should return previous week's Tuesday
    schedule = {"type": "weekly", "weekday": 1, "hour": 12, "minute": 0}
    expected = datetime(2021, 8, 3, 12, 0)
    assert compute_target(schedule, now) == expected


def test_monthly_day_exists_same_month():
    now = datetime(2021, 3, 15, 10, 0)
    schedule = {"type": "monthly", "day": 10, "hour": 9, "minute": 0}
    expected = datetime(2021, 3, 10, 9, 0)
    assert compute_target(schedule, now) == expected


def test_monthly_day_does_not_exist_uses_previous_month():
    # April 2021 has no 31st -> should fall back to March 31
    now = datetime(2021, 4, 15, 10, 0)
    schedule = {"type": "monthly", "day": 31, "hour": 10, "minute": 0}
    expected = datetime(2021, 3, 31, 10, 0)
    assert compute_target(schedule, now) == expected


def test_monthly_future_day_goes_previous_month():
    now = datetime(2021, 3, 1, 9, 0)
    # asking for day 15 which is later in the month should return previous month's 15th
    schedule = {"type": "monthly", "day": 15, "hour": 8, "minute": 0}
    expected = datetime(2021, 2, 15, 8, 0)
    assert compute_target(schedule, now) == expected


def test_unknown_schedule_type_raises():
    now = datetime(2026, 1, 29, 10, 0)
    schedule = {"type": "yearly", "month": 1, "day": 1}
    with pytest.raises(ValueError):
        compute_target(schedule, now)
