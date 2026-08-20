from __future__ import annotations

from datetime import date

from obsidian_ai_hub.planner import cache
from obsidian_ai_hub.planner import apple
from obsidian_ai_hub.planner import recurring
from obsidian_ai_hub.utils import config as app_config


class FakeClock:
    def __init__(self, start):
        self.now = start

    def time(self):
        return self.now


def test_cache_ttl_and_invalidation(monkeypatch):
    key = ("apple", "2026-08-01", "2026-08-31")
    clock = FakeClock(1000.0)
    monkeypatch.setattr(cache.time, "time", clock.time)

    cache.put_cached(key, {"value": 1})
    assert cache.get_cached(key) == {"value": 1}

    clock.now += cache.CACHE_TTL_SECONDS + 1
    assert cache.get_cached(key) is None

    cache.put_cached(key, {"value": 2})
    cache.invalidate(key)
    assert cache.get_cached(key) is None


def test_cache_invalidate_all(monkeypatch):
    cache.put_cached(("a",), 1)
    cache.put_cached(("b",), 2)
    cache.invalidate_all()
    assert cache.get_cached(("a",)) is None
    assert cache.get_cached(("b",)) is None


def test_cached_or_fetch_calls_fetcher_once():
    key = ("k",)
    calls = []

    def fetcher():
        calls.append(1)
        return "payload"

    assert cache.cached_or_fetch(key, fetcher) == "payload"
    assert cache.cached_or_fetch(key, fetcher) == "payload"
    assert len(calls) == 1


def test_get_external_data_cached_per_range(monkeypatch):
    from datetime import date

    fetched = []

    def fake_fetch(start, end):
        fetched.append((start, end))
        return {"calendar_events": [{"title": "A"}], "reminders": [], "error": None}

    monkeypatch.setattr(apple, "_fetch_external_raw", fake_fetch)

    r1 = apple.get_external_data(date(2026, 8, 1), date(2026, 8, 31))
    r2 = apple.get_external_data(date(2026, 8, 1), date(2026, 8, 31))
    assert r1 == r2
    assert len(fetched) == 1

    apple.get_external_data(date(2026, 9, 1), date(2026, 9, 30))
    assert len(fetched) == 2


def test_get_external_data_invalidate_refetches(monkeypatch):
    from datetime import date

    calls = {"n": 0}

    def fake_fetch(start, end):
        calls["n"] += 1
        return {"calendar_events": [], "reminders": [], "error": None}

    monkeypatch.setattr(apple, "_fetch_external_raw", fake_fetch)

    apple.get_external_data(date(2026, 8, 1), date(2026, 8, 31))
    apple.invalidate_cache()
    apple.get_external_data(date(2026, 8, 1), date(2026, 8, 31))
    assert calls["n"] == 2


def test_external_fetch_failure_degrades_to_empty_lists(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("EventKit exploded")

    monkeypatch.setattr(apple, "fetch_calendar_events", boom)
    monkeypatch.setattr(apple, "fetch_incomplete_reminders", boom)

    result = apple.get_external_data(date(2026, 8, 1), date(2026, 8, 31))
    assert result == {
        "calendar_events": [],
        "reminders": [],
        "error": "EventKit exploded",
    }


def test_expand_recurring_weekday_rule(monkeypatch):
    monkeypatch.setattr(app_config, "REGULARLY_WEEKDAY_EVENTS", [[[1], ["土"], 0, "司会", 2]])
    monkeypatch.setattr(app_config, "REGULARLY_DATE_EVENTS", [])

    items = recurring.expand_recurring(date(2026, 1, 1), date(2026, 1, 31))
    dates = [(i["date"], i["title"], i["kind"]) for i in items]
    assert (date(2026, 1, 3), "司会", "event") in dates
    assert len(items) == 1


def test_expand_recurring_date_rule_last_day(monkeypatch):
    monkeypatch.setattr(app_config, "REGULARLY_WEEKDAY_EVENTS", [])
    monkeypatch.setattr(app_config, "REGULARLY_DATE_EVENTS", [[[0], 0, "来月のノート作成", 1]])

    items = recurring.expand_recurring(date(2026, 1, 1), date(2026, 1, 31))
    assert items == [
        {
            "title": "来月のノート作成",
            "date": date(2026, 1, 31),
            "category": 1,
            "kind": "task",
            "source": "recurring",
            "start_time": None,
            "end_time": None,
            "all_day": True,
        }
    ]


def test_expand_recurring_category_mapping(monkeypatch):
    monkeypatch.setattr(app_config, "REGULARLY_WEEKDAY_EVENTS", [])
    monkeypatch.setattr(app_config, "REGULARLY_DATE_EVENTS", [[[15], 0, "月例ミーティング", 2]])

    items = recurring.expand_recurring(date(2026, 2, 1), date(2026, 2, 28))
    assert len(items) == 1
    assert items[0]["date"] == date(2026, 2, 15)
    assert items[0]["kind"] == "event"
    assert items[0]["category"] == 2


def test_expand_recurring_respects_day_offset(monkeypatch):
    # Fire one day after the rule date (offset 1).
    monkeypatch.setattr(app_config, "REGULARLY_WEEKDAY_EVENTS", [])
    monkeypatch.setattr(app_config, "REGULARLY_DATE_EVENTS", [[[15], 1, "翌日タスク", 1]])

    items = recurring.expand_recurring(date(2026, 3, 1), date(2026, 3, 31))
    dates = [i["date"] for i in items]
    assert date(2026, 3, 16) in dates
    assert date(2026, 3, 15) not in dates


def test_expand_recurring_empty_and_reversed_range(monkeypatch):
    monkeypatch.setattr(app_config, "REGULARLY_WEEKDAY_EVENTS", [[[1], ["月"], 0, "朝会", 2]])
    monkeypatch.setattr(app_config, "REGULARLY_DATE_EVENTS", [])

    assert recurring.expand_recurring(date(2026, 1, 10), date(2026, 1, 5)) == []
    items = recurring.expand_recurring(date(2026, 1, 5), date(2026, 1, 5))
    assert [i["title"] for i in items] == ["朝会"]


def test_expand_recurring_malformed_rules_skipped(monkeypatch):
    monkeypatch.setattr(app_config, "REGULARLY_WEEKDAY_EVENTS", [[[1], ["土"]]])
    monkeypatch.setattr(app_config, "REGULARLY_DATE_EVENTS", [[[0], 0]])
    assert recurring.expand_recurring(date(2026, 1, 1), date(2026, 1, 10)) == []