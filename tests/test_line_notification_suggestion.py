from __future__ import annotations


from obsidian_ai_hub.line_notification import (
    build_suggestion_link,
    notify_research_suggestion,
)


def test_research_suggestion_is_published_to_the_audited_inbox():
    """A proposal remains visible even when no external channel is enabled."""
    assert notify_research_suggestion(theme="調査テーマ", run_id="hrun_suggest_12") is False

    # The public research notifier, rather than a LINE-only helper, owns this record.
    from obsidian_ai_hub.notifications.store import list_inbox_notifications
    item = list_inbox_notifications()["items"][0]
    assert item["event_type"] == "research_suggestion"
    assert item["target_id"] == "hrun_suggest_12"
    assert item["relative_link"] == "/hitl?run_id=hrun_suggest_12"
    assert item["line_status"] == "skipped"
    assert item["web_push_status"] == "skipped"


class TestBuildSuggestionLink:
    def test_builds_hitl_deep_link_with_encoded_run_id(self):
        url = build_suggestion_link("https://aihub.tail744355.ts.net", "hrun_suggest_12")
        assert url == "https://aihub.tail744355.ts.net/hitl?run_id=hrun_suggest_12"

    def test_encodes_special_characters_in_run_id(self):
        url = build_suggestion_link("https://aihub.tail744355.ts.net", "hrun a/b?c=1")
        assert "?run_id=hrun%20a%2Fb%3Fc%3D1" in url

    def test_strips_trailing_slash_from_base(self):
        url = build_suggestion_link("https://aihub.tail744355.ts.net/", "hrun_1")
        assert url == "https://aihub.tail744355.ts.net/hitl?run_id=hrun_1"
