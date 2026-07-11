from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub import review_draft


DRAFT = """## 今週の達成
- 進めた

## 目標の振り返り
- 確認した

## 気づき・学び
- 学んだ

## 改善したいこと
- 整理する

## 来週の一歩
- 着手する"""


def _configure(monkeypatch, tmp_path, weekly_note, daily_notes):
    weekly_path = tmp_path / "2026-W28.md"
    monkeypatch.setattr(review_draft.reader, "get_weekly_note_content", lambda _: weekly_note)
    monkeypatch.setattr(review_draft.reader, "get_weekly_note_path", lambda _: weekly_path)
    monkeypatch.setattr(
        review_draft.reader,
        "get_daily_note_path",
        lambda day: daily_notes.get(day.strftime("%Y-%m-%d"), tmp_path / "missing.md"),
    )
    monkeypatch.setattr(review_draft.config, "REVIEW_DRAFT_PROMPT_PATH", tmp_path / "review_draft.md")
    monkeypatch.setattr(review_draft.config, "REVIEW_DRAFT_PROVIDER", "test-provider")
    monkeypatch.setattr(review_draft.config, "REVIEW_DRAFT_MODEL", "test-model")
    monkeypatch.setattr(review_draft.config, "LINE_MESSAGING_TOKEN", "token")
    monkeypatch.setattr(review_draft.config, "LINE_TARGET_ID", "target")
    return weekly_path


def test_creates_saves_and_sends_review_draft(monkeypatch, tmp_path):
    monday = tmp_path / "2026-07-06.md"
    wednesday = tmp_path / "2026-07-08.md"
    monday.write_text("Monday note", encoding="utf-8")
    wednesday.write_text("Wednesday note", encoding="utf-8")
    weekly_note = "# Weekly\nresult::\n\n## Goal\n- Ship it\n"
    weekly_path = _configure(
        monkeypatch,
        tmp_path,
        weekly_note,
        {"2026-07-06": monday, "2026-07-08": wednesday},
    )

    with (
        patch.object(review_draft.prompt, "render_prompt", return_value="rendered") as render,
        patch.object(review_draft.llm_client, "generate_llm_response", return_value=DRAFT) as generate,
        patch.object(review_draft, "send_line_push", return_value=True) as send,
    ):
        assert review_draft.main("2026-07-12") is True

    assert render.call_args.args[1]["WEEKLY_NOTE"] == weekly_note
    assert "Monday note" in render.call_args.args[1]["DAILY_NOTES"]
    assert "Wednesday note" in render.call_args.args[1]["DAILY_NOTES"]
    generate.assert_called_once_with(
        provider="test-provider", model="test-model", prompt="rendered", max_tokens=8192
    )
    assert DRAFT in weekly_path.read_text(encoding="utf-8")
    send.assert_called_once_with("token", "target", DRAFT)


def test_skips_when_result_field_already_has_value(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, "result:: completed", {})

    with (
        patch.object(review_draft.llm_client, "generate_llm_response") as generate,
        patch.object(review_draft, "send_line_push") as send,
    ):
        assert review_draft.main("2026-07-12") is False

    generate.assert_not_called()
    send.assert_not_called()


def test_retries_line_with_saved_draft_without_regenerating(monkeypatch, tmp_path):
    weekly_note = (
        "result::\n"
        f"{review_draft.REVIEW_DRAFT_START_MARKER}\n{DRAFT}\n"
        f"{review_draft.REVIEW_DRAFT_END_MARKER}\n"
    )
    _configure(monkeypatch, tmp_path, weekly_note, {})

    with (
        patch.object(review_draft.llm_client, "generate_llm_response") as generate,
        patch.object(review_draft, "send_line_push", return_value=True) as send,
    ):
        assert review_draft.main("2026-07-12") is True

    generate.assert_not_called()
    send.assert_called_once_with("token", "target", DRAFT)


def test_no_daily_notes_does_not_generate_or_send(monkeypatch, tmp_path):
    weekly_path = _configure(monkeypatch, tmp_path, "result::", {})

    with (
        patch.object(review_draft.llm_client, "generate_llm_response") as generate,
        patch.object(review_draft, "send_line_push") as send,
    ):
        assert review_draft.main("2026-07-12") is False

    assert not weekly_path.exists()
    generate.assert_not_called()
    send.assert_not_called()


def test_empty_llm_response_does_not_save_or_send(monkeypatch, tmp_path):
    daily_note = tmp_path / "2026-07-06.md"
    daily_note.write_text("Monday note", encoding="utf-8")
    weekly_path = _configure(monkeypatch, tmp_path, "result::", {"2026-07-06": daily_note})

    with (
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
        patch.object(review_draft.prompt, "render_prompt", return_value="rendered"),
        patch.object(review_draft.llm_client, "generate_llm_response", return_value=DRAFT),
        patch.object(Path, "write_text", side_effect=OSError("disk full")),
        patch.object(review_draft, "send_line_push") as send,
    ):
        assert review_draft.main("2026-07-12") is False

    send.assert_not_called()
