from datetime import datetime

from obsidian_ai_hub.utils import config
from obsidian_ai_hub.utils.reader import get_weekly_note_path


def _relative_path(monkeypatch, tmp_path, dt):
    monkeypatch.setattr(config, "DAILY_PATH", tmp_path)
    return get_weekly_note_path(dt).relative_to(tmp_path).as_posix()


def test_weekly_note_path_uses_monday_month(monkeypatch, tmp_path):
    cases = [
        # Issue example: 2026-10-04 (Sun) belongs to W40 starting Mon 2026-09-28.
        (datetime(2026, 10, 4), "2026/09/2026-W40.md"),
        # Same ISO week, different calendar months, must resolve to one path.
        (datetime(2026, 9, 28), "2026/09/2026-W40.md"),
        (datetime(2026, 9, 30), "2026/09/2026-W40.md"),
        # Week fully inside one month keeps existing behavior.
        (datetime(2026, 7, 8), "2026/07/2026-W28.md"),
        # ISO year boundary: 2021-01-01 (Fri) is ISO 2020-W53,
        # Monday is 2020-12-28, so ISO year/file stay 2020-W53 in month 12.
        (datetime(2021, 1, 1), "2020/12/2020-W53.md"),
        (datetime(2020, 12, 28), "2020/12/2020-W53.md"),
        # ISO year boundary the other way: 2019-12-30 (Mon) is ISO 2020-W01,
        # so the path keeps ISO year 2020 while using Monday's month 12.
        (datetime(2019, 12, 30), "2020/12/2020-W01.md"),
        (datetime(2020, 1, 5), "2020/12/2020-W01.md"),
    ]
    for dt, expected in cases:
        assert _relative_path(monkeypatch, tmp_path, dt) == expected
