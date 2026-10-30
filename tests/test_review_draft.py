import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from obsidian_ai_hub import review_draft


DRAFT_5 = """## 今週の達成
- 進めた

## 目標の振り返り
- 確認した

## 気づき・学び
- 学んだ

## 改善したいこと
- 整理する

## 来週の一歩
- 着手する"""

DRAFT_6 = """## 今週の達成
- 進めた

## 目標の振り返り
- 確認した

## 気づき・学び
- 学んだ

## 改善したいこと
- 整理する

## Focus との関係
- Focus A に取り組んだ

## 来週の一歩
- 着手する"""

DRAFT = DRAFT_5


def _configure(monkeypatch, tmp_path, weekly_note, daily_notes):
    weekly_path = tmp_path / "2026-W28.md"
    monkeypatch.setattr(
        review_draft.reader, "get_weekly_note_content", lambda _: weekly_note
    )
    monkeypatch.setattr(
        review_draft.reader, "get_weekly_note_path", lambda _: weekly_path
    )
    monkeypatch.setattr(
        review_draft.reader,
        "get_daily_note_path",
        lambda day: daily_notes.get(day.strftime("%Y-%m-%d"), tmp_path / "missing.md"),
    )
    monkeypatch.setattr(
        review_draft.config, "REVIEW_DRAFT_PROMPT_PATH", tmp_path / "review_draft.md"
    )
    monkeypatch.setattr(review_draft.config, "REVIEW_DRAFT_PROVIDER", "test-provider")
    monkeypatch.setattr(review_draft.config, "REVIEW_DRAFT_MODEL", "test-model")
    monkeypatch.setattr(review_draft.config, "LINE_MESSAGING_TOKEN", "token")
    monkeypatch.setattr(review_draft.config, "LINE_TARGET_ID", "target")
    return weekly_path


def test_collect_coach_context_filtering_limits_and_ordering(monkeypatch):
    monkeypatch.setattr(review_draft.config, "REVIEW_DRAFT_MAX_GOALS", 2)
    monkeypatch.setattr(review_draft.config, "REVIEW_DRAFT_MAX_FOCUSES_PER_GOAL", 2)

    goals = [
        {"goal_id": "g1", "statement": "Goal 1", "reason": "Reason 1", "status": "active", "created_at": "2026-07-10T10:00:00"},
        {"goal_id": "g2", "statement": "Goal 2", "reason": "", "status": "active", "created_at": "2026-07-09T10:00:00"},
        {"goal_id": "g3", "statement": "Goal 3", "reason": "", "status": "active", "created_at": "2026-07-08T10:00:00"},
    ]

    focuses_g1 = [
        {"focus_id": "f1", "goal_id": "g1", "name": "Focus Old", "status": "active", "created_at": "2026-07-01T00:00:00"},
        {"focus_id": "f2", "goal_id": "g1", "name": "Focus Mid", "status": "paused", "created_at": "2026-07-02T00:00:00"},
        {"focus_id": "f3", "goal_id": "g1", "name": "Focus Newest", "status": "active", "created_at": "2026-07-03T00:00:00"},
        {"focus_id": "f4", "goal_id": "g1", "name": "Focus Candidate", "status": "candidate", "created_at": "2026-07-04T00:00:00"},
    ]

    focuses_g2 = [
        {"focus_id": "f5", "goal_id": "g2", "name": "Focus G2 Active", "status": "active", "created_at": "2026-07-01T00:00:00"},
    ]

    mock_conn = MagicMock()
    mock_store = MagicMock()
    mock_store.list_goals.return_value = goals

    def _list_focuses(conn, goal_id):
        if goal_id == "g1":
            return focuses_g1
        if goal_id == "g2":
            return focuses_g2
        return []

    mock_store.list_focuses_by_goal.side_effect = _list_focuses

    with (
        patch("obsidian_ai_hub.database.get_db_connection", return_value=mock_conn),
        patch("obsidian_ai_hub.coach.store.CoachStore", return_value=mock_store),
    ):
        ctx = review_draft._collect_coach_context()

    assert mock_store.list_goals.call_args.kwargs == {"status": "active"}
    assert "Goal 1" in ctx
    assert "Goal 2" in ctx
    assert "Goal 3" not in ctx  # max_goals=2
    assert "Focus Newest (status: active)" in ctx
    assert "Focus Mid (status: paused)" in ctx
    assert "Focus Old" not in ctx  # max_focuses_per_goal=2 (newest 2 selected)
    assert "Focus Candidate" not in ctx  # candidate status excluded
    assert "Focus G2 Active (status: active)" in ctx


def test_collect_coach_context_returns_empty_when_no_active_goals_or_no_eligible_focuses():
    mock_conn = MagicMock()
    mock_store = MagicMock()
    mock_store.list_goals.return_value = [
        {"goal_id": "g1", "statement": "Goal 1", "status": "active", "created_at": "2026-07-01T00:00:00"}
    ]
    # Only candidate focuses exist
    mock_store.list_focuses_by_goal.return_value = [
        {"focus_id": "f1", "goal_id": "g1", "name": "Candidate", "status": "candidate", "created_at": "2026-07-01T00:00:00"}
    ]

    with (
        patch("obsidian_ai_hub.database.get_db_connection", return_value=mock_conn),
        patch("obsidian_ai_hub.coach.store.CoachStore", return_value=mock_store),
    ):
        assert review_draft._collect_coach_context() == ""


def test_collect_coach_context_logs_warning_and_returns_empty_on_exception(caplog):
    with (
        patch("obsidian_ai_hub.database.get_db_connection", side_effect=RuntimeError("DB error")),
        caplog.at_level(logging.WARNING),
    ):
        res = review_draft._collect_coach_context()

    assert res == ""
    assert "Failed to collect Coach context for review draft: DB error" in caplog.text


def test_has_expected_format_validation():
    assert review_draft._has_expected_format(DRAFT_5, expect_coach=False) is True
    assert review_draft._has_expected_format(DRAFT_5, expect_coach=True) is False
    assert review_draft._has_expected_format(DRAFT_6, expect_coach=True) is True
    assert review_draft._has_expected_format(DRAFT_6, expect_coach=False) is True

    out_of_order = """## 来週の一歩
- 着手する

## 今週の達成
- 進めた

## 目標の振り返り
- 確認した

## 気づき・学び
- 学んだ

## 改善したいこと
- 整理する"""
    assert review_draft._has_expected_format(out_of_order, expect_coach=False) is False


def test_creates_saves_and_sends_review_draft_with_coach_context(monkeypatch, tmp_path):
    monday = tmp_path / "2026-07-06.md"
    monday.write_text("Monday note", encoding="utf-8")
    weekly_note = "# Weekly\nresult::\n\n## Goal\n- Ship it\n"
    weekly_path = _configure(
        monkeypatch,
        tmp_path,
        weekly_note,
        {"2026-07-06": monday},
    )

    coach_block = "【参考: Coach の Goal / Focus】\n- Goal: Ship app\n  - Focus: Quality (status: active)"

    with (
        patch.object(review_draft, "_collect_coach_context", return_value=coach_block) as collect_mock,
        patch.object(
            review_draft.prompt, "render_prompt", return_value="rendered"
        ) as render,
        patch.object(
            review_draft.llm_client, "generate_llm_response", return_value=DRAFT_6
        ) as generate,
        patch.object(review_draft, "send_line_push", return_value=True) as send,
    ):
        assert review_draft.main("2026-07-12") is True

    collect_mock.assert_called_once()
    assert render.call_args.args[1]["COACH_CONTEXT"] == coach_block
    generate.assert_called_once_with(
        provider="test-provider", model="test-model", prompt="rendered", max_tokens=16384
    )
    assert DRAFT_6 in weekly_path.read_text(encoding="utf-8")
    send.assert_called_once_with("token", "target", DRAFT_6)


def test_creates_saves_and_sends_review_draft_when_coach_context_is_empty(monkeypatch, tmp_path):
    monday = tmp_path / "2026-07-06.md"
    monday.write_text("Monday note", encoding="utf-8")
    weekly_note = "# Weekly\nresult::\n\n## Goal\n- Ship it\n"
    weekly_path = _configure(
        monkeypatch,
        tmp_path,
        weekly_note,
        {"2026-07-06": monday},
    )

    with (
        patch.object(review_draft, "_collect_coach_context", return_value="") as collect_mock,
        patch.object(
            review_draft.prompt, "render_prompt", return_value="rendered"
        ) as render,
        patch.object(
            review_draft.llm_client, "generate_llm_response", return_value=DRAFT_5
        ) as generate,
        patch.object(review_draft, "send_line_push", return_value=True) as send,
    ):
        assert review_draft.main("2026-07-12") is True

    collect_mock.assert_called_once()
    assert render.call_args.args[1]["COACH_CONTEXT"] == ""
    assert DRAFT_5 in weekly_path.read_text(encoding="utf-8")
    send.assert_called_once_with("token", "target", DRAFT_5)


def test_rejects_draft_missing_coach_heading_when_coach_context_present(monkeypatch, tmp_path, caplog):
    monday = tmp_path / "2026-07-06.md"
    monday.write_text("Monday note", encoding="utf-8")
    _configure(monkeypatch, tmp_path, "# Weekly\nresult::\n", {"2026-07-06": monday})

    with (
        patch.object(review_draft, "_collect_coach_context", return_value="Coach block"),
        patch.object(review_draft.prompt, "render_prompt", return_value="rendered"),
        # LLM returns 5-heading draft instead of required 6-heading draft
        patch.object(review_draft.llm_client, "generate_llm_response", return_value=DRAFT_5),
        patch.object(review_draft, "send_line_push") as send,
        caplog.at_level(logging.WARNING),
    ):
        assert review_draft.main("2026-07-12") is False

    send.assert_not_called()
    assert "LLM response did not use the required weekly review headings" in caplog.text


def test_saved_draft_retry_path_untouched_for_both_5_and_6_headings(monkeypatch, tmp_path):
    weekly_note_5 = (
        "result::\n"
        f"{review_draft.REVIEW_DRAFT_START_MARKER}\n{DRAFT_5}\n"
        f"{review_draft.REVIEW_DRAFT_END_MARKER}\n"
    )
    _configure(monkeypatch, tmp_path, weekly_note_5, {})

    with (
        patch.object(review_draft, "_collect_coach_context") as collect_mock,
        patch.object(review_draft.llm_client, "generate_llm_response") as generate,
        patch.object(review_draft, "send_line_push", return_value=True) as send,
    ):
        assert review_draft.main("2026-07-12") is True

    collect_mock.assert_not_called()
    generate.assert_not_called()
    send.assert_called_once_with("token", "target", DRAFT_5)

    # Test 6-heading saved draft
    weekly_note_6 = (
        "result::\n"
        f"{review_draft.REVIEW_DRAFT_START_MARKER}\n{DRAFT_6}\n"
        f"{review_draft.REVIEW_DRAFT_END_MARKER}\n"
    )
    _configure(monkeypatch, tmp_path, weekly_note_6, {})

    with (
        patch.object(review_draft, "_collect_coach_context") as collect_mock,
        patch.object(review_draft.llm_client, "generate_llm_response") as generate,
        patch.object(review_draft, "send_line_push", return_value=True) as send,
    ):
        assert review_draft.main("2026-07-12") is True

    collect_mock.assert_not_called()
    generate.assert_not_called()
    send.assert_called_once_with("token", "target", DRAFT_6)


def test_skips_when_result_field_already_has_value(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, "result:: completed", {})

    with (
        patch.object(review_draft, "_collect_coach_context") as collect_mock,
        patch.object(review_draft.llm_client, "generate_llm_response") as generate,
        patch.object(review_draft, "send_line_push") as send,
    ):
        assert review_draft.main("2026-07-12") is False

    collect_mock.assert_not_called()
    generate.assert_not_called()
    send.assert_not_called()


def test_no_daily_notes_does_not_generate_or_send(monkeypatch, tmp_path):
    weekly_path = _configure(monkeypatch, tmp_path, "result::", {})

    with (
        patch.object(review_draft, "_collect_coach_context") as collect_mock,
        patch.object(review_draft.llm_client, "generate_llm_response") as generate,
        patch.object(review_draft, "send_line_push") as send,
    ):
        assert review_draft.main("2026-07-12") is False

    assert not weekly_path.exists()
    collect_mock.assert_not_called()
    generate.assert_not_called()
    send.assert_not_called()


def test_empty_llm_response_does_not_save_or_send(monkeypatch, tmp_path):
    daily_note = tmp_path / "2026-07-06.md"
    daily_note.write_text("Monday note", encoding="utf-8")
    weekly_path = _configure(
        monkeypatch, tmp_path, "result::", {"2026-07-06": daily_note}
    )

    with (
        patch.object(review_draft, "_collect_coach_context", return_value=""),
        patch.object(review_draft.prompt, "render_prompt", return_value="rendered"),
        patch.object(review_draft.llm_client, "generate_llm_response", return_value=""),
        patch.object(review_draft, "send_line_push") as send,
    ):
        assert review_draft.main(datetime(2026, 7, 12)) is False

    assert not weekly_path.exists()
    send.assert_not_called()


def test_write_failure_does_not_send(monkeypatch, tmp_path):
    daily_note = tmp_path / "2026-07-06.md"
    daily_note.write_text("Monday note", encoding="utf-8")
    _configure(monkeypatch, tmp_path, "result::", {"2026-07-06": daily_note})

    with (
        patch.object(review_draft, "_collect_coach_context", return_value=""),
        patch.object(review_draft.prompt, "render_prompt", return_value="rendered"),
        patch.object(
            review_draft.llm_client, "generate_llm_response", return_value=DRAFT_5
        ),
        patch.object(Path, "write_text", side_effect=OSError("disk full")),
        patch.object(review_draft, "send_line_push") as send,
    ):
        assert review_draft.main("2026-07-12") is False

    send.assert_not_called()
