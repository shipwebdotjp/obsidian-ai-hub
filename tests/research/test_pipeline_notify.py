from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl import get_run
from obsidian_ai_hub.research.pipeline import create_theme_and_research


def test_auto_suggestion_sends_notification_after_commit(test_memory_db_path: Path):
    theme = "通知テストテーマ"
    committed_at_notify: list[bool] = []

    def _assert_committed(*, run_id: str, **_kwargs) -> None:
        conn = get_db_connection()
        try:
            run = get_run(run_id, conn)
            committed_at_notify.append(run is not None)
        finally:
            conn.close()

    with patch(
        "obsidian_ai_hub.line_notification.notify_research_suggestion",
        side_effect=_assert_committed,
    ) as mock_notify:
        result = create_theme_and_research(
            theme=theme,
            direction="方向",
            kind="explore",
            is_suggestion=True,
        )

    assert result["status"] == "candidate"
    mock_notify.assert_called_once()
    # The run must already be committed and visible when the notification fires.
    assert committed_at_notify == [True]
    kwargs = mock_notify.call_args.kwargs
    assert kwargs["run_id"] == result["hitl_run_id"]
    assert kwargs["theme"] == theme


def test_notify_failure_does_not_fail_run_creation(test_memory_db_path: Path):
    theme = "通知失敗テーマ"
    with patch(
        "obsidian_ai_hub.line_notification.notify_research_suggestion",
        side_effect=RuntimeError("boom"),
    ) as mock_notify:
        result = create_theme_and_research(
            theme=theme,
            direction="方向",
            kind="explore",
            is_suggestion=True,
        )

    assert result["status"] == "candidate"
    assert result["hitl_run_id"]
    mock_notify.assert_called_once()

    conn = get_db_connection()
    try:
        run = get_run(result["hitl_run_id"], conn)
        assert run is not None
        assert run["status"] == "pending_user"
    finally:
        conn.close()


def test_manual_research_does_not_send_notification(test_memory_db_path: Path):
    theme = "手動リサーチテーマ"
    with (
        patch("obsidian_ai_hub.line_notification.notify_research_suggestion") as mock_notify,
        patch("obsidian_ai_hub.research.runner.run_theme_research") as mock_run,
    ):
        result = create_theme_and_research(
            theme=theme,
            direction="方向",
            kind="explore",
            is_suggestion=False,
        )

    assert result["status"] == "candidate"
    mock_notify.assert_not_called()
    mock_run.assert_called_once()


def test_duplicate_theme_does_not_send_notification(test_memory_db_path: Path):
    theme = "重複通知テストテーマ"
    with patch(
        "obsidian_ai_hub.line_notification.notify_research_suggestion"
    ) as mock_notify:
        first = create_theme_and_research(
            theme=theme,
            direction="方向",
            kind="explore",
            is_suggestion=True,
        )
        second = create_theme_and_research(
            theme=theme,
            direction="方向",
            kind="explore",
            is_suggestion=True,
        )

    assert first["status"] == "candidate"
    assert second["status"] == "duplicate"
    # Only the first (non-duplicate) registration notifies.
    mock_notify.assert_called_once()