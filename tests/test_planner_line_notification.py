from __future__ import annotations

from unittest.mock import patch

from obsidian_ai_hub.line_notification import planner as planner_notify


def test_build_planner_summary_text_with_proposals():
    proposals = [
        {
            "kind": "calendar",
            "title": "歯科検診",
            "start_time": "2026-08-26T10:00:00",
        },
        {"kind": "reminder", "title": "本を返す", "due_date": "2026-08-20"},
        {"kind": "calendar", "title": "日付未定の提案", "start_time": None},
    ]
    text = planner_notify.build_planner_summary_text(proposals, "http://localhost:8765")

    assert "AIプランナーが新しい提案を作成しました" in text
    assert "[予定] 歯科検診 (2026-08-26)" in text
    assert "[リマインダー] 本を返す (2026-08-20)" in text
    assert "[予定] 日付未定の提案 (日付未定)" in text
    assert "http://localhost:8765/planner" in text


def test_build_planner_summary_text_empty():
    text = planner_notify.build_planner_summary_text([], "")
    assert "ありませんでした" in text


def test_notify_planner_summary_delegates_to_push_best_effort():
    proposals = [{"kind": "calendar", "title": "歯科検診", "start_time": None}]
    with patch.object(
        planner_notify, "push_best_effort", return_value=True
    ) as mock_push:
        ok = planner_notify.notify_planner_summary(proposals, web_url="http://x")

    assert ok is True
    assert mock_push.call_count == 1
    builder = mock_push.call_args.args[0]
    assert "歯科検診" in builder("http://x")