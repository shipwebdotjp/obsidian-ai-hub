import sys
from unittest.mock import MagicMock, patch
import pytest
from pathlib import Path

@pytest.fixture
def mock_dependencies():
    mock_modules = {
        "dotenv": MagicMock(),
        "yaml": MagicMock(),
        "AppKit": MagicMock(),
        "objc": MagicMock(),
        "whisper": MagicMock(),
        "langchain_core": MagicMock(),
        "langchain_openai": MagicMock(),
        "langchain_tavily": MagicMock(),
        "ApplicationServices": MagicMock(),
        "Quartz": MagicMock(),
        "Vision": MagicMock(),
        "Cocoa": MagicMock(),
        "Foundation": MagicMock(),
        "wurlitzer": MagicMock(),
        "pydantic": MagicMock(),
        "langchain_core.tools": MagicMock(),
        "langchain_core.messages": MagicMock(),
        "sentence_transformers": MagicMock(),
    }
    with patch.dict(sys.modules, mock_modules):
        yield

def test_prompt_externalization_wiring(mock_dependencies):
    # Test a few modules to ensure they are correctly wired to use the new prompt paths
    from obsidian_ai_hub import scan_line_inbox, logging_activity, summerize_day
    from obsidian_ai_hub.utils import config

    # scan_line_inbox
    with patch("obsidian_ai_hub.scan_line_inbox.accessibility") as mock_acc, \
         patch("obsidian_ai_hub.scan_line_inbox.take_screenshot") as mock_ts, \
         patch("obsidian_ai_hub.scan_line_inbox.img2text") as mock_i2t, \
         patch("obsidian_ai_hub.scan_line_inbox.prompt") as mock_prompt, \
         patch("obsidian_ai_hub.scan_line_inbox.llm_client") as mock_llm:

        mock_acc.get_line_window.return_value = {"window_id": 123, "window_title": "LINE"}
        mock_ts.main.return_value = "dummy.png"
        mock_i2t.image_to_text.return_value = [("text", 0.9)]
        mock_prompt.render_prompt.return_value = "Rendered Prompt"
        mock_llm.generate_llm_response.return_value = '{"candidates": []}'

        scan_line_inbox.scan_line_inbox()

        mock_prompt.render_prompt.assert_called_once()
        assert mock_prompt.render_prompt.call_args[0][0] == config.LINE_INBOX_SCAN_PROMPT_PATH

    # logging_activity
    with patch("obsidian_ai_hub.logging_activity.accessibility") as mock_acc, \
         patch("obsidian_ai_hub.logging_activity.NSScreen") as mock_ns, \
         patch("obsidian_ai_hub.logging_activity.img2text") as mock_i2t, \
         patch("obsidian_ai_hub.logging_activity.prompt") as mock_prompt, \
         patch("obsidian_ai_hub.logging_activity.llm_client") as mock_llm, \
         patch("obsidian_ai_hub.logging_activity.capture_screen"), \
         patch("obsidian_ai_hub.logging_activity.get_unique_path"), \
         patch("builtins.open", MagicMock()):

        mock_acc.get_active_window_info.return_value = {"app_name": "Finder", "window_title": "Home"}
        mock_ns.screens.return_value = []
        mock_prompt.render_prompt.return_value = "Rendered Prompt"
        mock_llm.generate_llm_response.return_value = "{}"

        logging_activity.main()

        mock_prompt.render_prompt.assert_called_once()
        assert mock_prompt.render_prompt.call_args[0][0] == config.ACTIVITY_CLASSIFICATION_PROMPT_PATH

    # summerize_day
    with patch("obsidian_ai_hub.summerize_day.llm_client") as mock_llm, \
         patch("obsidian_ai_hub.summerize_day.prompt") as mock_prompt, \
         patch("obsidian_ai_hub.summerize_day.reader") as mock_reader:

        mock_reader.get_daily_note_path.return_value = Path("dummy.md")
        mock_prompt.render_prompt.return_value = "Rendered Prompt"
        mock_llm.generate_llm_response.return_value = "{}"

        from datetime import datetime
        summerize_day.get_daily_structured_record(datetime.now(), "content", [], [])

        mock_prompt.render_prompt.assert_called_once()
        assert mock_prompt.render_prompt.call_args[0][0] == config.SUMMARIZE_DAY_PROMPT_PATH

    # summerize_week
    from obsidian_ai_hub import summerize_week
    with patch("obsidian_ai_hub.summerize_week.llm_client") as mock_llm, \
         patch("obsidian_ai_hub.summerize_week.prompt") as mock_prompt:

        mock_prompt.render_prompt.return_value = "Rendered Prompt"
        mock_llm.generate_llm_response.return_value = "{}"

        summerize_week.get_weekly_structured_record(datetime.now(), [])

        mock_prompt.render_prompt.assert_called_once()
        assert mock_prompt.render_prompt.call_args[0][0] == config.SUMMARIZE_WEEK_PROMPT_PATH

    # summerize_month
    from obsidian_ai_hub import summerize_month
    with patch("obsidian_ai_hub.summerize_month.llm_client") as mock_llm, \
         patch("obsidian_ai_hub.summerize_month.prompt") as mock_prompt:

        mock_prompt.render_prompt.return_value = "Rendered Prompt"
        mock_llm.generate_llm_response.return_value = "{}"

        summerize_month.get_monthly_structured_record(datetime.now(), [])

        mock_prompt.render_prompt.assert_called_once()
        assert mock_prompt.render_prompt.call_args[0][0] == config.SUMMARIZE_MONTH_PROMPT_PATH

    # research_agent router
    from obsidian_ai_hub import research_agent
    with patch("obsidian_ai_hub.research_agent.prompt") as mock_prompt, \
         patch("obsidian_ai_hub.research_agent.llm_client") as mock_llm:

        mock_prompt.render_prompt.return_value = "Rendered Prompt"
        mock_llm.generate_llm_response.return_value = "web"

        research_agent.build_web_research_router_prompt("theme")

        mock_prompt.render_prompt.assert_called_once()
        assert mock_prompt.render_prompt.call_args[0][0] == config.RESEARCH_ROUTER_PROMPT_PATH
