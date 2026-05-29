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


def test_cron_syntax_step():
    now = datetime(2026, 1, 29, 10, 15, 30)
    # */5 means 0, 5, 10, 15, 20...
    schedule = {"type": "minutely", "second": "*/5"}
    expected = datetime(2026, 1, 29, 10, 15, 30)
    assert compute_target(schedule, now) == expected


def test_cron_syntax_list():
    now = datetime(2026, 1, 29, 10, 15, 30)
    schedule = {"type": "minutely", "second": "0,20,40"}
    # latest <= 30 is 20
    expected = datetime(2026, 1, 29, 10, 15, 20)
    assert compute_target(schedule, now) == expected


def test_cron_syntax_range():
    now = datetime(2026, 1, 29, 10, 15, 30)
    schedule = {"type": "minutely", "second": "31-33"}
    # latest <= 30 in [31,32,33] is 33 of PREVIOUS minute
    expected = datetime(2026, 1, 29, 10, 14, 33)
    assert compute_target(schedule, now) == expected


def test_yaml_array():
    now = datetime(2026, 1, 29, 10, 15, 30)
    schedule = {"type": "minutely", "second": [0, 20, 40]}
    expected = datetime(2026, 1, 29, 10, 15, 20)
    assert compute_target(schedule, now) == expected


def test_error_invalid_range():
    now = datetime(2026, 1, 29, 10, 0)
    schedule = {"type": "minutely", "second": "10-5"}
    with pytest.raises(ValueError, match="Invalid range"):
        compute_target(schedule, now)


def test_error_zero_step():
    now = datetime(2026, 1, 29, 10, 0)
    schedule = {"type": "minutely", "second": "*/0"}
    with pytest.raises(ValueError, match="Step must be positive"):
        compute_target(schedule, now)


def test_error_out_of_bounds():
    now = datetime(2026, 1, 29, 10, 0)
    schedule = {"type": "minutely", "second": 60}
    with pytest.raises(ValueError, match="out of range"):
        compute_target(schedule, now)


def test_latest_execution_only():
    # If multiple execution times passed, should return the LATEST one.
    # This is handled by compute_target returning the single latest target <= now.
    now = datetime(2026, 1, 29, 10, 15, 30)
    schedule = {"type": "minutely", "second": "*/10"}
    # Times: 0, 10, 20, 30, 40, 50
    # At 10:15:30, target should be 10:15:30.
    # If last_run was 10:15:05, it will run because 10:15:05 < 10:15:30.
    assert compute_target(schedule, now) == datetime(2026, 1, 29, 10, 15, 30)

    now2 = datetime(2026, 1, 29, 10, 15, 39)
    assert compute_target(schedule, now2) == datetime(2026, 1, 29, 10, 15, 30)


def test_hourly_multi_field_cron():
    now = datetime(2026, 1, 29, 10, 15, 30)
    # 0,30 minutes, 0 seconds
    schedule = {"type": "hourly", "minute": "0,30", "second": 0}
    # latest <= 10:15:30 is 10:00:00
    expected = datetime(2026, 1, 29, 10, 0, 0)
    assert compute_target(schedule, now) == expected

    now2 = datetime(2026, 1, 29, 10, 35, 0)
    # latest <= 10:35:00 is 10:30:00
    expected2 = datetime(2026, 1, 29, 10, 30, 0)
    assert compute_target(schedule, now2) == expected2


def test_daily_step_hour():
    now = datetime(2026, 1, 29, 10, 15, 30)
    # every 6 hours (0, 6, 12, 18), 0 min, 0 sec
    schedule = {"type": "daily", "hour": "*/6", "minute": 0, "second": 0}
    # latest <= 10:15 is 06:00
    expected = datetime(2026, 1, 29, 6, 0, 0)
    assert compute_target(schedule, now) == expected


def test_weekly_range_weekday():
    # 2026-01-29 is Thursday (weekday=3)
    now = datetime(2026, 1, 29, 10, 0, 0)
    # Monday-Wednesday (0-2), at 09:00
    schedule = {"type": "weekly", "weekday": "0-2", "hour": 9, "minute": 0}
    # latest <= Thursday 10:00 is Wednesday 09:00
    expected = datetime(2026, 1, 28, 9, 0, 0)
    assert compute_target(schedule, now) == expected


def test_monthly_list_day():
    now = datetime(2026, 1, 29, 10, 0, 0)
    # 1st and 15th, at 09:00
    schedule = {"type": "monthly", "day": "1,15", "hour": 9, "minute": 0}
    # latest <= Jan 29 is Jan 15
    expected = datetime(2026, 1, 15, 9, 0, 0)
    assert compute_target(schedule, now) == expected


def test_cross_field_boundary_backtrack():
    now = datetime(2026, 1, 29, 0, 5, 0)
    # Every hour at minute 10
    schedule = {"type": "hourly", "minute": 10}
    # latest <= 00:05:00 is 23:10:00 of previous day
    expected = datetime(2026, 1, 28, 23, 10, 0)
    assert compute_target(schedule, now) == expected


def test_complex_yaml_array_multi_field():
    now = datetime(2026, 1, 29, 10, 0, 0)
    schedule = {
        "type": "daily",
        "hour": [8, 12, 16],
        "minute": [0, 30]
    }
    # latest <= 10:00:00 is 08:30:00
    expected = datetime(2026, 1, 29, 8, 30, 0)
    assert compute_target(schedule, now) == expected
