from __future__ import annotations


from obsidian_ai_hub.line_notification import (
    build_suggestion_link,
)


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
