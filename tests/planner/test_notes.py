from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from obsidian_ai_hub.planner import notes
from obsidian_ai_hub.utils import reader

NOTE = """---
title: 2026-10-29
tags:
  - daily
---
[[2026-10]]

```dataviewjs
await dv.view("views/dailynavigation",{})
```
# 2026/10/29 木曜日
## ☀️ 今日の天気
☀️   晴天 +14.9°C
## 🚩今日の目標
- 週末までに講演の準備を終える
## 📅 今日の予定
- レッスン参加 10:00~11:00
## ✅ 今日のタスク
- [ ] 本を図書館に返す
- [ ] 
## 🏃‍♀️ 習慣トラッカー
- [ ] 要約や言い換えした
- [ ] 感情ラベルした
## 💡 今日の気づき・振り返り
### 🌟 良かったこと・できたこと
- 午前中は講演の準備を進めた。
### 🤔 改善点・反省点
- 集中できていなかった。
## 📝メモ
歯科検診の予約を入れる
## 📍今日の移動
- 10:00 自宅
"""


def test_extract_citable_lines_keeps_intentions_and_memos_only():
    lines = notes.extract_citable_lines(NOTE)

    assert "週末までに講演の準備を終える" in lines
    assert "本を図書館に返す" in lines
    assert "歯科検診の予約を入れる" in lines
    # machine-written / reflection / template lines are not evidence
    for excluded in (
        "レッスン参加 10:00~11:00",
        "要約や言い換えした",
        "感情ラベルした",
        "午前中は講演の準備を進めた。",
        "集中できていなかった。",
        "10:00 自宅",
        "晴天 +14.9°C",
    ):
        assert excluded not in lines


def test_extract_citable_lines_ignores_frontmatter_and_code_fences():
    lines = notes.extract_citable_lines(NOTE)

    assert all("dataviewjs" not in line for line in lines)
    assert all("title:" not in line for line in lines)


def test_extract_citable_lines_returns_empty_for_template_only_note():
    template = """# <% tp.date.now("YYYY/MM/DD dddd") %>
## 🚩今日の目標
## ✅今日のタスク
- [ ] 
## 📝メモ
## 📍今日の移動
"""

    assert notes.extract_citable_lines(template) == []


def test_collect_citable_lines_reads_existing_files_only(tmp_path: Path):
    day = date(2026, 10, 29)
    existing = tmp_path / "2026-10-29.md"
    existing.write_text(NOTE, encoding="utf-8")
    missing = tmp_path / "2026-10-28.md"

    def fake_path(value: date) -> Path:
        return existing if value == day else missing

    with patch.object(reader, "get_daily_note_path", side_effect=fake_path):
        lines = notes.collect_citable_lines(days=2, reference_date=day)

    assert [line.ref for line in lines] == ["E1", "E2", "E3"]
    assert all(line.date == day for line in lines)


def test_collect_citable_lines_dedupes_repeated_text(tmp_path: Path):
    day = date(2026, 10, 29)
    yesterday = date(2026, 10, 28)
    older = tmp_path / "2026-10-28.md"
    older.write_text("## 📝メモ\n歯科検診の予約を入れる", encoding="utf-8")
    newest = tmp_path / "2026-10-29.md"
    newest.write_text("## 📝メモ\n歯科検診の予約を入れる", encoding="utf-8")

    def fake_path(value: date) -> Path:
        return newest if value == day else older

    with patch.object(reader, "get_daily_note_path", side_effect=fake_path):
        lines = notes.collect_citable_lines(days=2, reference_date=day)

    assert len(lines) == 1
    assert lines[0].date == day


def test_collect_citable_lines_rejects_non_positive_days():
    with pytest.raises(ValueError):
        notes.collect_citable_lines(days=0)


def test_find_line_by_quote_normalizes_punctuation_and_spacing():
    lines = [
        notes.EvidenceLine(
            ref="E1", date=date(2026, 10, 29), text="歯科検診の予約を入れる。"
        )
    ]

    assert notes.find_line_by_quote("歯科検診の予約", lines) is not None
    assert notes.find_line_by_quote("存在しない引用", lines) is None
    assert notes.find_line_by_quote("歯科", lines) is None


def test_collect_citable_lines_survives_an_unreadable_day(tmp_path: Path):
    day = date(2026, 10, 29)
    readable = tmp_path / "2026-10-28.md"
    readable.write_text("## 📝メモ\n歯科検診の予約を入れる", encoding="utf-8")

    def fake_path(value: date) -> Path:
        if value == day:
            raise PermissionError("denied")
        return readable

    with patch.object(reader, "get_daily_note_path", side_effect=fake_path):
        lines = notes.collect_citable_lines(days=2, reference_date=day)

    assert [line.text for line in lines] == ["歯科検診の予約を入れる"]
