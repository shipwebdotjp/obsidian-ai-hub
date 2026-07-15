from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub import research_agent
from obsidian_ai_hub import research_themes


def test_run_research_returns_report_without_saving_to_vault():
    with (
        patch.object(research_agent, "collect_research_context", return_value=""),
        patch.object(research_agent, "route_research_topic", return_value="internal"),
        patch.object(research_agent.llm_client, "generate_llm_response", return_value="mocked response"),
        patch.object(research_agent, "conduct_research", return_value="mocked report"),
    ):
        report = research_agent.run_research("test theme")

    assert report.title is not None
    assert report.mode == "internal"
    assert "mocked report" in report.markdown


def test_run_theme_research_succeeds():
    rec = research_themes.create_theme(theme="テスト調査", kind="deep", confidence=0.8)

    with (
        patch.object(research_agent, "collect_research_context", return_value=""),
        patch.object(research_agent, "route_research_topic", return_value="internal"),
        patch.object(research_agent.llm_client, "generate_llm_response", return_value="mocked title"),
        patch.object(research_agent, "conduct_research", return_value="mocked report"),
    ):
        job = research_agent.run_theme_research(rec["theme_id"])

    assert job is not None
    assert job["status"] == "succeeded"
    assert job["generated_title"] is not None
    assert job["markdown"] is not None


def test_run_theme_research_fails_keeps_theme_candidate():
    rec = research_themes.create_theme(theme="失敗テスト", kind="explore", confidence=0.5)

    with (
        patch.object(research_agent, "collect_research_context", return_value=""),
        patch.object(research_agent, "route_research_topic", return_value="internal"),
        patch.object(research_agent.llm_client, "generate_llm_response", side_effect=RuntimeError("fail")),
    ):
        job = research_agent.run_theme_research(rec["theme_id"])

    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] is not None

    theme = research_themes.get_theme(rec["theme_id"])
    assert theme["status"] == "candidate"


def test_save_research_to_vault(tmp_path: Path):
    rec = research_themes.create_theme(theme="Vault保存テスト", kind="deep", confidence=0.9)
    from obsidian_ai_hub.research_agent import run_theme_research

    with (
        patch.object(research_agent, "collect_research_context", return_value=""),
        patch.object(research_agent, "route_research_topic", return_value="internal"),
        patch.object(research_agent.llm_client, "generate_llm_response", return_value="テストタイトル"),
        patch.object(research_agent, "conduct_research", return_value="テストレポート本文"),
    ):
        run_theme_research(rec["theme_id"])

    output_dir = tmp_path / "research"
    with (
        patch.object(research_agent.config, "RESEARCH_OUTPUT_DIR", output_dir),
    ):
        saved_path = research_agent.save_research_to_vault(rec["theme_id"])

    assert saved_path is not None
    assert saved_path.exists()
    content = saved_path.read_text(encoding="utf-8")
    assert "テストレポート本文" in content


def test_main_creates_theme_and_researches(tmp_path: Path):
    from obsidian_ai_hub import research_themes

    output_dir = tmp_path / "research"
    with (
        patch.object(research_agent, "collect_research_context", return_value=""),
        patch.object(research_agent, "route_research_topic", return_value="internal"),
        patch.object(research_agent.llm_client, "generate_llm_response", return_value="mocked"),
        patch.object(research_agent, "conduct_research", return_value="report"),
        patch.object(research_agent.config, "RESEARCH_OUTPUT_DIR", output_dir),
    ):
        result = research_agent.main(theme="CLIテーマ")

    assert result.success_count == 1
    assert result.error_count == 0

    themes = research_themes.list_themes()
    approved = [t for t in themes if "CLIテーマ" in t["theme"]]
    assert len(approved) == 1
    assert approved[0]["status"] == "approved"
    assert any(output_dir.iterdir())


def test_main_failure_keeps_approved_status():
    from obsidian_ai_hub import research_themes

    with (
        patch.object(research_agent, "collect_research_context", return_value=""),
        patch.object(research_agent, "route_research_topic", return_value="internal"),
        patch.object(research_agent.llm_client, "generate_llm_response", side_effect=RuntimeError("fail")),
    ):
        result = research_agent.main(theme="失敗テーマ")

    assert result.success_count == 0
    assert result.error_count == 1

    themes = research_themes.list_themes()
    failed = [t for t in themes if "失敗テーマ" in t["theme"]]
    assert len(failed) == 1
    assert failed[0]["status"] == "approved"
    job = failed[0].get("latest_job")
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] is not None


def test_main_reuses_existing_approved_theme(tmp_path: Path):
    from obsidian_ai_hub import research_themes

    output_dir = tmp_path / "research2"

    with (
        patch.object(research_agent, "collect_research_context", return_value=""),
        patch.object(research_agent, "route_research_topic", return_value="internal"),
        patch.object(research_agent.llm_client, "generate_llm_response", return_value="mocked"),
        patch.object(research_agent, "conduct_research", return_value="report1"),
        patch.object(research_agent.config, "RESEARCH_OUTPUT_DIR", output_dir),
    ):
        result1 = research_agent.main(theme="再利用テーマ")
        assert result1.success_count == 1

    themes1 = research_themes.list_themes()
    themes1 = [t for t in themes1 if "再利用テーマ" in t["theme"]]
    assert len(themes1) == 1
    first_id = themes1[0]["theme_id"]

    with (
        patch.object(research_agent, "collect_research_context", return_value=""),
        patch.object(research_agent, "route_research_topic", return_value="internal"),
        patch.object(research_agent.llm_client, "generate_llm_response", return_value="mocked_v2"),
        patch.object(research_agent, "conduct_research", return_value="report2"),
        patch.object(research_agent.config, "RESEARCH_OUTPUT_DIR", output_dir),
    ):
        result2 = research_agent.main(theme="再利用テーマ")
        assert result2.success_count == 1

    themes2 = research_themes.list_themes()
    themes2 = [t for t in themes2 if "再利用テーマ" in t["theme"]]
    assert len(themes2) == 1  # Same theme reused
    assert themes2[0]["theme_id"] == first_id


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
