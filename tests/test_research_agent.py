from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub import research_agent


def test_main_queue_mode_completes_successfully(tmp_path: Path):
    candidate_path = tmp_path / "research_candidates.md"
    output_dir = tmp_path / "research_output"
    candidate_path.write_text("- [ ] test theme\n", encoding="utf-8")

    with (
        patch.object(research_agent.config, "RESEARCH_CANDIDATE_THEME_LIST_PATH", candidate_path),
        patch.object(research_agent.config, "RESEARCH_OUTPUT_DIR", output_dir),
        patch.object(research_agent, "collect_research_context", return_value=""),
        patch.object(research_agent, "route_research_topic", return_value="internal"),
        patch.object(research_agent.llm_client, "generate_llm_response", return_value="mocked response"),
        patch.object(research_agent, "conduct_research", return_value="mocked report"),
    ):
        result = research_agent.main()

    assert result.success_count == 1
    assert result.error_count == 0
    assert any(output_dir.iterdir())  # Check that some file was created
    assert "- [x] test theme" in candidate_path.read_text(encoding="utf-8")


def test_main_on_demand_mode_completes_successfully(tmp_path: Path):
    output_dir = tmp_path / "research_output"

    with (
        patch.object(research_agent.config, "RESEARCH_OUTPUT_DIR", output_dir),
        patch.object(research_agent, "collect_research_context", return_value=""),
        patch.object(research_agent, "route_research_topic", return_value="internal"),
        patch.object(research_agent.llm_client, "generate_llm_response", return_value="mocked response"),
        patch.object(research_agent, "conduct_research", return_value="mocked report"),
    ):
        result = research_agent.main(theme="on demand theme")

    assert result.success_count == 1
    assert result.error_count == 0
    assert any(output_dir.iterdir())


def test_research_uses_the_provider_and_model_for_each_llm_role():
    with (
        patch.object(research_agent.config, "RESEARCH_ROUTER_PROVIDER", "router-provider"),
        patch.object(research_agent.config, "RESEARCH_ROUTER_MODEL", "router-model"),
        patch.object(research_agent.config, "RESEARCH_TITLE_GENERATION_PROVIDER", "title-provider"),
        patch.object(research_agent.config, "RESEARCH_TITLE_GENERATION_MODEL", "title-model"),
        patch.object(research_agent.config, "RESEARCH_INTERNAL_PROVIDER", "internal-provider"),
        patch.object(research_agent.config, "RESEARCH_INTERNAL_MODEL", "internal-model"),
        patch.object(research_agent.llm_client, "generate_llm_response", return_value="internal") as mock_response,
    ):
        research_agent.route_research_topic("topic")
        research_agent.generate_research_title("topic", "prompt")
        research_agent.conduct_research("prompt", mode="internal")

    assert mock_response.call_args_list[0].kwargs["provider"] == "router-provider"
    assert mock_response.call_args_list[0].kwargs["model"] == "router-model"
    assert mock_response.call_args_list[1].kwargs["provider"] == "title-provider"
    assert mock_response.call_args_list[1].kwargs["model"] == "title-model"
    assert mock_response.call_args_list[2].kwargs["provider"] == "internal-provider"
    assert mock_response.call_args_list[2].kwargs["model"] == "internal-model"


def test_web_research_uses_its_own_provider_and_model():
    with (
        patch.object(research_agent.config, "RESEARCH_WEB_PROVIDER", "web-provider"),
        patch.object(research_agent.config, "RESEARCH_WEB_MODEL", "web-model"),
        patch.object(research_agent.llm_client, "generate_llm_response_with_tools", return_value="report") as mock_response,
    ):
        assert research_agent.conduct_research("prompt", mode="web") == "report"

    assert mock_response.call_args.kwargs["provider"] == "web-provider"
    assert mock_response.call_args.kwargs["model"] == "web-model"


def test_gpt_researcher_environment_uses_config_and_restores_prior_values(monkeypatch):
    monkeypatch.setenv("FAST_LLM", "original-fast")
    monkeypatch.delenv("SMART_LLM", raising=False)

    with (
        patch.object(research_agent.config, "RESEARCH_GPT_RESEARCHER_FAST_LLM", "configured-fast"),
        patch.object(research_agent.config, "RESEARCH_GPT_RESEARCHER_SMART_LLM", "configured-smart"),
    ):
        with research_agent._gpt_researcher_environment():
            assert os.environ["FAST_LLM"] == "configured-fast"
            assert os.environ["SMART_LLM"] == "configured-smart"

    assert os.environ["FAST_LLM"] == "original-fast"
    assert "SMART_LLM" not in os.environ
