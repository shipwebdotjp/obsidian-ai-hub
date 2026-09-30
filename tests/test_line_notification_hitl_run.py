from __future__ import annotations

from unittest.mock import patch

from obsidian_ai_hub.line_notification import (
    build_hitl_run_text,
    notify_hitl_run,
)
from obsidian_ai_hub.notifications.store import update_notification_settings


class TestNotifyHitlRun:
    def test_returns_false_and_logs_when_config_missing(self, caplog):
        update_notification_settings(
            line_enabled=True,
            line_action_required=True,
        )
        with patch("obsidian_ai_hub.utils.line_messaging.send_line_push") as m:
            ok = notify_hitl_run(
                kind="長期記憶保守",
                title="診断メンテナンス",
                description="",
                run_id="mem_maint_1",
                line_token="",
                line_target="",
                web_url="",
            )
        assert ok is False
        m.assert_not_called()
        assert "LINE notification skipped" in caplog.text

    def test_sends_single_push_on_success(self, monkeypatch):
        update_notification_settings(
            line_enabled=True,
            line_action_required=True,
        )
        monkeypatch.setattr("obsidian_ai_hub.utils.config.LINE_MESSAGING_TOKEN", "tok")
        monkeypatch.setattr("obsidian_ai_hub.utils.config.LINE_TARGET_ID", "uid")
        monkeypatch.setattr("obsidian_ai_hub.utils.config.OBSIDIAN_AI_HUB_WEB_URL", "https://aihub.tail744355.ts.net")
        with patch(
            "obsidian_ai_hub.utils.line_messaging.send_line_push",
            return_value=True,
        ) as mock_send:
            ok = notify_hitl_run(
                kind="長期記憶保守",
                title="診断メンテナンス",
                description="説明文",
                run_id="mem_maint_1",
                line_token="tok",
                line_target="uid",
                web_url="https://aihub.tail744355.ts.net",
                round_number=2,
            )
        assert ok is True
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "【要対応】長期記憶保守の再提案（ラウンド 2）" in text
        assert "対象: 診断メンテナンス" in text
        assert "https://aihub.tail744355.ts.net/hitl?run_id=mem_maint_1" in text

    def test_default_web_url_used_when_none_passed(self, monkeypatch):
        update_notification_settings(
            line_enabled=True,
            line_action_required=True,
        )
        default_url = "https://aihub.tail744355.ts.net"
        monkeypatch.setattr("obsidian_ai_hub.utils.config.LINE_MESSAGING_TOKEN", "tok")
        monkeypatch.setattr("obsidian_ai_hub.utils.config.LINE_TARGET_ID", "uid")
        monkeypatch.setattr("obsidian_ai_hub.utils.config.OBSIDIAN_AI_HUB_WEB_URL", default_url)
        with patch(
            "obsidian_ai_hub.utils.line_messaging.send_line_push",
            return_value=True,
        ) as mock_send:
            ok = notify_hitl_run(
                kind="週次メモリインタビュー",
                title="週次メモリインタビュー",
                description="",
                run_id="mem_interview_2026-W33",
                line_token="tok",
                line_target="uid",
            )
        assert ok is True
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "【要対応】週次メモリインタビューの確認が必要です" in text
        assert default_url in text

    def test_push_failure_logs_warning_without_secrets(self, caplog, monkeypatch):
        update_notification_settings(
            line_enabled=True,
            line_action_required=True,
        )
        monkeypatch.setattr("obsidian_ai_hub.utils.config.LINE_MESSAGING_TOKEN", "tok")
        monkeypatch.setattr("obsidian_ai_hub.utils.config.LINE_TARGET_ID", "uid")
        monkeypatch.setattr("obsidian_ai_hub.utils.config.OBSIDIAN_AI_HUB_WEB_URL", "https://aihub.tail744355.ts.net")
        with patch(
            "obsidian_ai_hub.utils.line_messaging.send_line_push",
            side_effect=RuntimeError("tok 秘密の説明"),
        ) as mock_send:
            ok = notify_hitl_run(
                kind="長期記憶保守",
                title="診断メンテナンス",
                description="秘密の説明",
                run_id="mem_maint_1",
                line_token="tok",
                line_target="uid",
                web_url="https://aihub.tail744355.ts.net",
            )
        assert ok is False
        mock_send.assert_called_once()
        assert "LINE notification push failed" in caplog.text
        assert "tok" not in caplog.text
        assert "秘密の説明" not in caplog.text

    def test_push_false_response_returns_false_without_raising(self, caplog, monkeypatch):
        update_notification_settings(
            line_enabled=True,
            line_action_required=True,
        )
        monkeypatch.setattr("obsidian_ai_hub.utils.config.LINE_MESSAGING_TOKEN", "tok")
        monkeypatch.setattr("obsidian_ai_hub.utils.config.LINE_TARGET_ID", "uid")
        monkeypatch.setattr("obsidian_ai_hub.utils.config.OBSIDIAN_AI_HUB_WEB_URL", "https://aihub.tail744355.ts.net")
        with patch(
            "obsidian_ai_hub.utils.line_messaging.send_line_push",
            return_value=False,
        ) as mock_send:
            ok = notify_hitl_run(
                kind="長期記憶保守",
                title="診断メンテナンス",
                description="説明文",
                run_id="mem_maint_1",
                line_token="tok",
                line_target="uid",
                web_url="https://aihub.tail744355.ts.net",
            )
        assert ok is False
        mock_send.assert_called_once()
        assert "LINE notification push failed" in caplog.text
