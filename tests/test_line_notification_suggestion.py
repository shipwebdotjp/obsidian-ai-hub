from __future__ import annotations

from unittest.mock import patch

from obsidian_ai_hub.line_notification import (
    build_research_suggestion_text,
    build_suggestion_link,
    notify_research_suggestion,
)


class TestBuildSuggestionLink:
    def test_builds_hitl_deep_link_with_encoded_run_id(self):
        url = build_suggestion_link("https://aihub.tail744355.ts.net", "hrun_suggest_12")
        assert url == "https://aihub.tail744355.ts.net/hitl?run_id=hrun_suggest_12"

    def test_encodes_special_characters_in_run_id(self):
        url = build_suggestion_link("https://aihub.tail744355.ts.net", "hrun a/b?c=1")
        assert "?run_id=hrun%20a%2Fb%3Fc%3D1" in url

    def test_encodes_hash_and_plus_in_run_id(self):
        url = build_suggestion_link("https://aihub.tail744355.ts.net", "hrun+#x")
        assert "?run_id=hrun%2B%23x" in url

    def test_strips_trailing_slash_from_base(self):
        url = build_suggestion_link("https://aihub.tail744355.ts.net/", "hrun_1")
        assert url == "https://aihub.tail744355.ts.net/hitl?run_id=hrun_1"


class TestBuildResearchSuggestionText:
    def test_includes_theme_and_link(self):
        text = build_research_suggestion_text(
            "Obsidianの整理", "hrun_suggest_5", "https://aihub.tail744355.ts.net"
        )
        assert "Obsidianの整理" in text
        assert "https://aihub.tail744355.ts.net/hitl?run_id=hrun_suggest_5" in text

    def test_empty_web_url_omits_link_line(self):
        text = build_research_suggestion_text("テーマ", "hrun_1", "")
        assert "テーマ" in text
        assert "/hitl" not in text


class TestNotifyResearchSuggestion:
    def test_returns_false_and_logs_when_config_missing(self, caplog):
        with patch("obsidian_ai_hub.utils.line_messaging.send_line_push") as m:
            ok = notify_research_suggestion(
                theme="テーマ", run_id="hrun_1", line_token="", line_target="", web_url=""
            )
        assert ok is False
        m.assert_not_called()
        assert "notification skipped" in caplog.text

    def test_sends_single_push_on_success(self):
        with patch(
            "obsidian_ai_hub.utils.line_messaging.send_line_push",
            return_value=True,
        ) as mock_send:
            ok = notify_research_suggestion(
                theme="テーマ",
                run_id="hrun_1",
                line_token="tok",
                line_target="uid",
                web_url="https://aihub.tail744355.ts.net",
            )
        assert ok is True
        mock_send.assert_called_once_with(
            "tok",
            "uid",
            build_research_suggestion_text(
                "テーマ", "hrun_1", "https://aihub.tail744355.ts.net"
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
            ok = notify_research_suggestion(
                theme="テーマ", run_id="hrun_1", line_token="tok", line_target="uid"
            )
        assert ok is True
        mock_send.assert_called_once_with(
            "tok",
            "uid",
            build_research_suggestion_text("テーマ", "hrun_1", default_url),
        )

    def test_push_failure_logs_warning_without_secrets(self, caplog):
        with patch(
            "obsidian_ai_hub.utils.line_messaging.send_line_push",
            side_effect=RuntimeError("boom"),
        ) as mock_send:
            ok = notify_research_suggestion(
                theme="テーマ",
                run_id="hrun_1",
                line_token="tok",
                line_target="uid",
                web_url="https://aihub.tail744355.ts.net",
            )
        assert ok is False
        mock_send.assert_called_once()
        assert "push failed" in caplog.text
        assert "tok" not in caplog.text
        assert "テーマ" not in caplog.text