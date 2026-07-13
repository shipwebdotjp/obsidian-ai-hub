import sys
from datetime import datetime
from unittest.mock import MagicMock, patch, mock_open
import pytest

def test_make_today_target_main():
    # Mock modules using patch.dict to avoid contamination
    mock_modules = {
        "dotenv": MagicMock(),
        "yaml": MagicMock(),
        "langchain_core": MagicMock(),
        "langchain_core.messages": MagicMock(),
        "langchain_core.tools": MagicMock(),
        "langchain_openai": MagicMock(),
        "langchain_google_genai": MagicMock(),
        "langchain_community": MagicMock(),
        "langchain_anthropic": MagicMock(),
    }

    with patch.dict(sys.modules, mock_modules):
        from obsidian_ai_hub import make_today_target

        with patch("obsidian_ai_hub.make_today_target.reader") as mock_reader, \
             patch("obsidian_ai_hub.make_today_target.extracter") as mock_extracter, \
             patch("obsidian_ai_hub.make_today_target.llm_client") as mock_llm, \
             patch("obsidian_ai_hub.make_today_target.prompt") as mock_prompt, \
             patch("obsidian_ai_hub.make_today_target.config") as mock_config:

            mock_reader.get_daily_note_content.return_value = "今日の目標\nExisting content"
            mock_reader.get_daily_note_path.return_value = "dummy_path.md"
            mock_extracter.get_subheader_view.return_value = "Subheader content"
            mock_extracter.get_frontmatter_value.return_value = "dummy"
            mock_prompt.render_prompt.return_value = "Rendered Prompt Content"
            mock_llm.generate_llm_response.return_value = "Generated Goal"
            mock_config.MAKE_TODAY_TARGET_PROMPT_PATH = "dummy_prompt.md"
            mock_config.MAKE_TODAY_TARGET_PROVIDER = "test_provider"
            mock_config.MAKE_TODAY_TARGET_MODEL = "test_model"

            m = mock_open()
            with patch("builtins.open", m):
                make_today_target.main()

                # Verify prompt rendering
                mock_prompt.render_prompt.assert_called_once()
                args, _ = mock_prompt.render_prompt.call_args
                assert args[0] == "dummy_prompt.md"
                assert "todays_schedule" in args[1]
                assert "todays_task" in args[1]
                assert "daily_context" in args[1]

                # Verify LLM call
                mock_llm.generate_llm_response.assert_called_once_with(
                    provider="test_provider",
                    model="test_model",
                    prompt="Rendered Prompt Content",
                    max_tokens=8192,
                    system_prompt=None
                )

                # Verify file write
                m.assert_called_with("dummy_path.md", "w")
                handle = m()
                handle.write.assert_called_once()
                written_content = handle.write.call_args[0][0]
                assert "今日の目標\n- [ ] Generated Goal" in written_content
