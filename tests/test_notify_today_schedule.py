import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from obsidian_ai_hub.line_notification import (
    format_summary_for_line,
    is_monday,
    prev_iso_week_key,
    build_daily_message_text,
    build_week_summary_text,
    build_message_texts,
    WEEK_KIND_LABELS,
)


def test_format_summary_with_summary_text_and_items():
    record = {
        "summary": "穏やかな一日だった。",
        "items": [
            {"kind": "highlights", "body": "大事な決断をした", "display_order": 0},
            {"kind": "activities", "body": "コーディング", "display_order": 0},
            {"kind": "learnings", "body": "Pythonの非同期処理を学んだ", "display_order": 0},
            {"kind": "reflections", "body": "もっと早く始めるべきだった", "display_order": 0},
            {"kind": "gratitude", "body": "家族に感謝", "display_order": 0},
        ],
    }
    result = format_summary_for_line(record)
    assert "💡要約" in result
    assert "穏やかな一日だった。" in result
    assert "【ハイライト】" in result
    assert "・大事な決断をした" in result
    assert "【活動内容】" in result
    assert "・コーディング" in result
    assert "【学び・整理】" in result
    assert "・Pythonの非同期処理を学んだ" in result
    assert "【反省・気づき】" in result
    assert "・もっと早く始めるべきだった" in result
    assert "【感謝】" in result
    assert "・家族に感謝" in result
    # Verify fixed kind order
    assert result.index("【ハイライト】") < result.index("【活動内容】")
    assert result.index("【活動内容】") < result.index("【学び・整理】")
    assert result.index("【学び・整理】") < result.index("【反省・気づき】")
    assert result.index("【反省・気づき】") < result.index("【感謝】")


def test_format_summary_same_kind_grouped_under_single_heading():
    record = {
        "summary": "忙しい一日",
        "items": [
            {"kind": "highlights", "body": "機能リリース", "display_order": 1},
            {"kind": "highlights", "body": "バグ修正", "display_order": 0},
            {"kind": "activities", "body": "コードレビュー", "display_order": 0},
        ],
    }
    result = format_summary_for_line(record)
    assert result.count("【ハイライト】") == 1
    assert result.count("【活動内容】") == 1
    # display_order within kind: バグ修正 (0) before 機能リリース (1)
    assert result.index("・バグ修正") < result.index("・機能リリース")


def test_format_summary_unknown_kind_included_at_end():
    record = {
        "summary": "新しい発見",
        "items": [
            {"kind": "highlights", "body": "完了", "display_order": 0},
            {"kind": "custom_kind", "body": "カスタム項目", "display_order": 0},
        ],
    }
    result = format_summary_for_line(record)
    assert "【ハイライト】" in result
    assert "【custom_kind】" in result
    assert result.index("【ハイライト】") < result.index("【custom_kind】")


def test_format_summary_no_summary_text_still_shows_items():
    record = {
        "summary": None,
        "items": [
            {"kind": "highlights", "body": "作業完了", "display_order": 0},
        ],
    }
    result = format_summary_for_line(record)
    assert "💡要約" not in result
    assert "【ハイライト】" in result
    assert "・作業完了" in result


def test_format_summary_empty_items_shows_only_summary():
    record = {
        "summary": "何もなかった一日",
        "items": [],
    }
    result = format_summary_for_line(record)
    assert "💡要約" in result
    assert "何もなかった一日" in result
    assert "【" not in result


def test_format_summary_empty_record_returns_empty():
    record = {
        "summary": None,
        "items": [],
    }
    result = format_summary_for_line(record)
    assert result == ""


def test_format_summary_with_week_kind_labels():
    """format_summary_for_line with WEEK_KIND_LABELS preserves summary and section order."""
    record = {
        "summary": "週の総括",
        "items": [
            {"kind": "highlights", "body": "リリース完了", "display_order": 0},
            {"kind": "progress", "body": "機能A 80%", "display_order": 0},
            {"kind": "learnings", "body": "新しい技術を習得", "display_order": 0},
            {"kind": "reflections", "body": "計画通り進んだ", "display_order": 0},
            {"kind": "patterns", "body": "午前中に集中", "display_order": 0},
            {"kind": "gratitude", "body": "チームに感謝", "display_order": 0},
        ],
    }
    result = format_summary_for_line(record, kind_labels=WEEK_KIND_LABELS)
    assert "週の総括" in result
    assert "リリース完了" in result
    assert "機能A 80%" in result
    # Compact ordering check: each kind's body appears in WEEK_KIND_LABELS order
    order_marker = "リリース完了"  # highlights
    positions = [
        result.index("リリース完了"),
        result.index("機能A 80%"),
        result.index("新しい技術を習得"),
        result.index("計画通り進んだ"),
        result.index("午前中に集中"),
        result.index("チームに感謝"),
    ]
    assert positions == sorted(positions), f"sections out of WEEK_KIND_LABELS order: {positions}"


def test_format_summary_people_and_projects_included():
    record = {
        "summary": "会議の多い一日",
        "items": [{"kind": "highlights", "body": "MTG", "display_order": 0}],
        "people": [
            {"name": "山田太郎", "note": "打ち合わせ"},
            {"name": "佐藤花子", "note": ""},
        ],
        "projects": ["プロジェクトA", "プロジェクトB"],
    }
    result = format_summary_for_line(record)
    assert "山田太郎" in result
    assert "打ち合わせ" in result
    assert "佐藤花子" in result
    assert "プロジェクトA" in result
    assert "プロジェクトB" in result


# --- is_monday ---

def test_is_monday_returns_true():
    assert is_monday(datetime(2026, 7, 20)) is True  # 2026-07-20 is Monday


def test_is_monday_returns_false():
    assert is_monday(datetime(2026, 7, 21)) is False  # Tuesday
    assert is_monday(datetime(2026, 7, 19)) is False  # Sunday


# --- prev_iso_week_key ---

def test_prev_iso_week_key_mid_week():
    # Wednesday 2026-07-22 -> Monday's Sunday is 2026-07-26
    # prev Sunday = 2026-07-19 -> ISO week 2026-W29
    key = prev_iso_week_key(datetime(2026, 7, 22))
    assert key == "2026-W29"


def test_prev_iso_week_key_monday():
    # Monday 2026-07-20 -> that week's Sunday = 2026-07-26
    # prev Sunday = 2026-07-19 -> ISO week 2026-W29
    key = prev_iso_week_key(datetime(2026, 7, 20))
    assert key == "2026-W29"


def test_prev_iso_week_key_cross_year():
    # Monday 2021-01-04 (ISO week 2021-W01)
    # that week's Sunday = 2021-01-10
    # prev Sunday = 2021-01-03 which is ISO week 2020-W53
    key = prev_iso_week_key(datetime(2021, 1, 4))
    assert key == "2020-W53"


# --- build_daily_message_text ---

DAILY_NOTE_WITH_ALL = """---
date: 2026-07-20
---
# 今日のノート

## ☀️ 今日の天気
晴れ

## 🚩今日の目標
タスクAを完了する

## 📅 今日の予定
10:00 会議

## ✅ 今日のタスク
- タスクA
- タスクB
"""


@patch("obsidian_ai_hub.line_notification.builder.store.get_summary_by_period")
@patch("obsidian_ai_hub.line_notification.builder.reader.get_daily_note_content")
def test_build_daily_message_text_with_all(
    mock_get_note, mock_get_summary
):
    mock_get_note.return_value = DAILY_NOTE_WITH_ALL
    mock_get_summary.return_value = {
        "summary": "良い一日だった",
        "items": [{"kind": "highlights", "body": "仕事完了", "display_order": 0}],
    }

    dt = datetime(2026, 7, 20)
    result = build_daily_message_text(dt)

    assert "良い一日だった" in result
    assert "晴れ" in result
    assert "タスクAを完了する" in result
    assert "10:00 会議" in result
    assert "タスクA" in result


@patch("obsidian_ai_hub.line_notification.builder.store.get_summary_by_period")
@patch("obsidian_ai_hub.line_notification.builder.reader.get_daily_note_content")
def test_build_daily_message_text_empty_note(
    mock_get_note, mock_get_summary
):
    mock_get_note.return_value = ""
    mock_get_summary.return_value = None

    dt = datetime(2026, 7, 20)
    result = build_daily_message_text(dt)
    assert result == ""


# --- build_week_summary_text ---

def test_build_week_summary_text_found():
    dt = datetime(2026, 7, 20)  # Monday
    expected_key = "2026-W29"
    week_record = {
        "summary": "週のまとめ",
        "items": [
            {"kind": "highlights", "body": "週間ハイライト", "display_order": 0},
            {"kind": "progress", "body": "進捗80%", "display_order": 0},
            {"kind": "learnings", "body": "学び", "display_order": 0},
            {"kind": "reflections", "body": "反省", "display_order": 0},
            {"kind": "patterns", "body": "パターン", "display_order": 0},
            {"kind": "gratitude", "body": "感謝", "display_order": 0},
        ],
    }

    with patch("obsidian_ai_hub.line_notification.builder.store.get_summary_by_period") as mock_get:
        mock_get.return_value = week_record
        result = build_week_summary_text(dt)

    mock_get.assert_called_once_with("week", expected_key)
    assert "週のまとめ" in result
    assert "週間ハイライト" in result
    assert "進捗80%" in result


def test_build_week_summary_text_not_found():
    dt = datetime(2026, 7, 20)
    with patch("obsidian_ai_hub.line_notification.builder.store.get_summary_by_period") as mock_get:
        mock_get.return_value = None
        result = build_week_summary_text(dt)

    assert result == ""


# --- build_message_texts ---

@patch("obsidian_ai_hub.line_notification.builder.build_daily_message_text")
@patch("obsidian_ai_hub.line_notification.builder.build_week_summary_text")
def test_build_message_texts_non_monday_daily_only(
    mock_weekly, mock_daily
):
    """Non-Monday: only daily message returned."""
    mock_daily.return_value = "今日の通知本文"
    mock_weekly.return_value = "週次本文"

    dt = datetime(2026, 7, 21)  # Tuesday
    texts = build_message_texts(dt)

    assert texts == ["今日の通知本文"]
    mock_weekly.assert_not_called()


@patch("obsidian_ai_hub.line_notification.builder.build_daily_message_text")
@patch("obsidian_ai_hub.line_notification.builder.build_week_summary_text")
def test_build_message_texts_monday_two_messages(
    mock_weekly, mock_daily
):
    """Monday with daily + weekly -> 2 messages."""
    mock_daily.return_value = "今日の通知本文"
    mock_weekly.return_value = "週次本文"

    dt = datetime(2026, 7, 20)  # Monday
    texts = build_message_texts(dt)

    assert texts == ["今日の通知本文", "週次本文"]


@patch("obsidian_ai_hub.line_notification.builder.build_daily_message_text")
@patch("obsidian_ai_hub.line_notification.builder.build_week_summary_text")
def test_build_message_texts_monday_no_weekly_still_sends_daily(
    mock_weekly, mock_daily
):
    """Monday but no week summary -> only daily."""
    mock_daily.return_value = "今日の通知本文"
    mock_weekly.return_value = ""

    dt = datetime(2026, 7, 20)  # Monday
    texts = build_message_texts(dt)

    assert texts == ["今日の通知本文"]


@patch("obsidian_ai_hub.line_notification.builder.build_daily_message_text")
@patch("obsidian_ai_hub.line_notification.builder.build_week_summary_text")
def test_build_message_texts_monday_no_daily_weekly_only(
    mock_weekly, mock_daily
):
    """Monday, daily empty, weekly exists -> only weekly."""
    mock_daily.return_value = ""
    mock_weekly.return_value = "週次本文"

    dt = datetime(2026, 7, 20)  # Monday
    texts = build_message_texts(dt)

    assert texts == ["週次本文"]


@patch("obsidian_ai_hub.line_notification.builder.build_daily_message_text")
@patch("obsidian_ai_hub.line_notification.builder.build_week_summary_text")
def test_build_message_texts_both_empty(mock_weekly, mock_daily):
    """Both empty -> empty list."""
    mock_daily.return_value = ""
    mock_weekly.return_value = ""

    dt = datetime(2026, 7, 20)  # Monday
    texts = build_message_texts(dt)

    assert texts == []
