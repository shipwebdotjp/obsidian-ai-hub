import pytest

from obsidian_ai_hub.notify_today_schedule import format_summary_for_line


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
    assert "💡昨日の要約" in result
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
    assert "💡昨日の要約" not in result
    assert "【ハイライト】" in result
    assert "・作業完了" in result


def test_format_summary_empty_items_shows_only_summary():
    record = {
        "summary": "何もなかった一日",
        "items": [],
    }
    result = format_summary_for_line(record)
    assert "💡昨日の要約" in result
    assert "何もなかった一日" in result
    assert "【" not in result


def test_format_summary_empty_record_returns_empty():
    record = {
        "summary": None,
        "items": [],
    }
    result = format_summary_for_line(record)
    assert result == ""
