from datetime import date


from obsidian_ai_hub.notify_calendar_event import get_days
from obsidian_ai_hub.notify_calendar_event import get_dates_in_month, is_today
from datetime import timedelta


def test_single_weekday_first_occurrence():
    # January 2026: Saturdays are 3,10,17,24,31 -> first Saturday is 3
    target = date(2026, 1, 29)
    days = get_days(target, days_number=[6], nthday=[1])
    assert days == [date(2026, 1, 3)]


def test_multiple_weekdays_multiple_nth():
    target = date(2021, 8, 10)
    days = get_days(target, days_number=[1, 0], nthday=[1, 3])

    expected = {
        date(2021, 8, 2),
        date(2021, 8, 16),
        date(2021, 8, 1),
        date(2021, 8, 15),
    }
    assert set(days) == expected


def test_empty_nthday_returns_empty():
    target = date(2021, 12, 1)
    days = get_days(target, days_number=[1, 2, 3], nthday=[])
    assert days == []


def test_month_with_fewer_occurrences():
    # February 2021 (non-leap): Sundays are 7,14,21,28 (no 5th)
    target = date(2021, 2, 10)
    # ask for 5th Sunday (nthday [5]) -> should be empty
    days = get_days(target, days_number=[0], nthday=[5])
    assert days == []


def test_get_dates_in_month_includes_valid_date():
    target = date(2026, 1, 29)
    days = get_dates_in_month(target, [1, 25, 29])
    assert date(2026, 1, 29) in days


def test_get_dates_in_month_skips_invalid_date():
    target = date(2021, 2, 10)  # 2021-02 has no 29
    days = get_dates_in_month(target, [28, 29])
    assert set(days) == {date(2021, 2, 28)}


def test_get_dates_in_month_allows_leap_day():
    target = date(2024, 2, 1)
    days = get_dates_in_month(target, [29])
    assert days == [date(2024, 2, 29)]


def test_day_offset_message_fire():
    # Simulate a REGULARLY_DATE_EVENTS-like check: if target_day (now - offset)
    # matches one of the dates, is_today should return True.
    now = date(2026, 1, 29)
    day_offset = 0
    target_day = now - timedelta(days=day_offset)
    target_days = get_dates_in_month(target_day, [29])
    assert is_today(target_day, target_days)


def test_get_dates_in_month_allows_zero_for_last_day():
    # February 2021 (non-leap): last day is 28
    target = date(2021, 2, 10)
    days = get_dates_in_month(target, [0])
    assert days == [date(2021, 2, 28)]
