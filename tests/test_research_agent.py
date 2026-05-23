from __future__ import annotations

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
