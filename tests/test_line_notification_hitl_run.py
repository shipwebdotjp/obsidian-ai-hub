from __future__ import annotations

from unittest.mock import patch

from obsidian_ai_hub.line_notification import (
    build_hitl_run_text,
    notify_hitl_run,
)


class TestNotifyHitlRun:
    def test_returns_false_and_logs_when_config_missing(self, caplog):
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
        assert "notification skipped" in caplog.text

    def test_sends_single_push_on_success(self):
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
        mock_send.assert_called_once_with(
            "tok",
            "uid",
            build_hitl_run_text(
                kind="長期記憶保守",
                title="診断メンテナンス",
                description="説明文",
                run_id="mem_maint_1",
                web_url="https://aihub.tail744355.ts.net",
                round_number=2,
            ),
        )

    def test_default_web_url_used_when_none_passed(self, monkeypatch):
        from obsidian_ai_hub.utils import config

        default_url = "https://aihub.tail744355.ts.net"
        monkeypatch.setattr(config, "OBSIDIAN_AI_HUB_WEB_URL", default_url)
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
        mock_send.assert_called_once_with(
            "tok",
            "uid",
            build_hitl_run_text(
                kind="週次メモリインタビュー",
                title="週次メモリインタビュー",
                description="",
                run_id="mem_interview_2026-W33",
                web_url=default_url,
            ),
        )

    def test_push_failure_logs_warning_without_secrets(self, caplog):
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
        assert "push failed" in caplog.text
        assert "tok" not in caplog.text
        assert "秘密の説明" not in caplog.text

    def test_push_false_response_returns_false_without_raising(self, caplog):
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
        assert "push failed" in caplog.text