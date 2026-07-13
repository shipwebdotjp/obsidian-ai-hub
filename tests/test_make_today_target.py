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
             patch("obsidian_ai_hub.make_today_target.config") as mock_config, \
             patch("obsidian_ai_hub.memory.compile_context") as mock_compile_ctx:

            mock_compile_ctx.return_value = {"context": ""}
            mock_reader.get_daily_note_content.return_value = "今日の目標\nExisting content"
            mock_reader.get_daily_note_path.return_value = "dummy_path.md"
            mock_extracter.get_subheader_view.return_value = "Subheader content"
            mock_extracter.get_frontmatter_value.return_value = "dummy"
            mock_llm.generate_llm_response.return_value = "Generated Goal"
            mock_config.MAKE_TODAY_TARGET_PROMPT_PATH = "dummy_prompt.md"
            mock_config.MAKE_TODAY_TARGET_PROVIDER = "test_provider"
            mock_config.MAKE_TODAY_TARGET_MODEL = "test_model"

            # Mock template file content
            template_text = "【今日の予定】\n${todays_schedule}\n【今日のタスク】\n${todays_task}\n【過去7日間の日記】\n${daily_context}\n"
            m = mock_open(read_data=template_text)
            with patch("builtins.open", m):
                make_today_target.main()

                # Verify file open for template reading
                m.assert_any_call("dummy_prompt.md", "r", encoding="utf-8")

                # Verify LLM call
                called_args, called_kwargs = mock_llm.generate_llm_response.call_args
                assert called_kwargs["provider"] == "test_provider"
                assert called_kwargs["model"] == "test_model"
                assert "Subheader content" in called_kwargs["prompt"]
                assert called_kwargs["max_tokens"] == 8192
                assert called_kwargs["system_prompt"] is None

                # Verify file write back
                m.assert_any_call("dummy_path.md", "w")
