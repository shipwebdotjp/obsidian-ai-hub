from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from obsidian_ai_hub.research import db as research_themes
from obsidian_ai_hub.research import runner


def test_run_theme_research_succeeds():
    rec = research_themes.create_theme(theme="テスト調査", kind="deep", confidence=0.8)

    with (
        patch.object(runner, "collect_research_context", return_value=""),
        patch.object(runner, "route_research_topic", return_value="internal"),
        patch.object(
            runner.llm_client, "generate_llm_response", return_value="mocked title"
        ),
        patch.object(runner, "conduct_research", return_value="mocked report"),
    ):
        job = runner.run_theme_research(rec["theme_id"])

    assert job is not None
    assert job["status"] == "succeeded"
    assert job["generated_title"] is not None
    assert job["markdown"] is not None


def test_run_theme_research_fails_keeps_theme_candidate():
    rec = research_themes.create_theme(
        theme="失敗テスト", kind="explore", confidence=0.5
    )

    with (
        patch.object(runner, "collect_research_context", return_value=""),
        patch.object(runner, "route_research_topic", return_value="internal"),
        patch.object(
            runner.llm_client, "generate_llm_response", side_effect=RuntimeError("fail")
        ),
    ):
        job = runner.run_theme_research(rec["theme_id"])

    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] is not None

    theme = research_themes.get_theme(rec["theme_id"])
    assert theme["status"] == "candidate"


def test_save_research_to_vault(tmp_path: Path):
    rec = research_themes.create_theme(
        theme="Vault保存テスト", kind="deep", confidence=0.9
    )

    with (
        patch.object(runner, "collect_research_context", return_value=""),
        patch.object(runner, "route_research_topic", return_value="internal"),
        patch.object(
            runner.llm_client, "generate_llm_response", return_value="テストタイトル"
        ),
        patch.object(runner, "conduct_research", return_value="テストレポート本文"),
    ):
        runner.run_theme_research(rec["theme_id"])

    output_dir = tmp_path / "research"
    with (
        patch.object(runner.config, "RESEARCH_OUTPUT_DIR", output_dir),
    ):
        saved_path = runner.save_research_to_vault(rec["theme_id"])

    assert saved_path is not None
    assert saved_path.exists()
    content = saved_path.read_text(encoding="utf-8")
    assert "テストレポート本文" in content


def test_main_creates_theme_and_researches(tmp_path: Path):
    output_dir = tmp_path / "research2"
    with (
        patch.object(runner, "collect_research_context", return_value=""),
        patch.object(runner, "route_research_topic", return_value="internal"),
        patch.object(runner.llm_client, "generate_llm_response", return_value="mocked"),
        patch.object(runner, "conduct_research", return_value="report"),
        patch.object(runner.config, "RESEARCH_OUTPUT_DIR", output_dir),
    ):
        result = runner.main(theme="CLIテーマ")

    assert result.success_count == 1
    assert result.error_count == 0

    themes = research_themes.list_themes()
    approved = [t for t in themes if "CLIテーマ" in t["theme"]]
    assert len(approved) == 1
    assert approved[0]["status"] == "approved"
    assert any(output_dir.iterdir())


def test_main_failure_keeps_candidate_status():
    with (
        patch.object(runner, "collect_research_context", return_value=""),
        patch.object(runner, "route_research_topic", return_value="internal"),
        patch.object(
            runner.llm_client, "generate_llm_response", side_effect=RuntimeError("fail")
        ),
    ):
        result = runner.main(theme="失敗テーマ")

    assert result.success_count == 0
    assert result.error_count == 1

    themes = research_themes.list_themes()
    failed = [t for t in themes if "失敗テーマ" in t["theme"]]
    assert len(failed) == 1
    assert failed[0]["status"] == "candidate"
    job = failed[0].get("latest_job")
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] is not None


def test_main_approved_theme_failure_keeps_approved_status():
    # 1. Create an approved theme first
    research_themes.create_theme(theme="既存承認済み失敗テーマ", status="approved")

    with (
        patch.object(runner, "collect_research_context", return_value=""),
        patch.object(runner, "route_research_topic", return_value="internal"),
        patch.object(
            runner.llm_client, "generate_llm_response", side_effect=RuntimeError("fail")
        ),
    ):
        result = runner.main(theme="既存承認済み失敗テーマ")

    assert result.success_count == 0
    assert result.error_count == 1

    themes = research_themes.list_themes()
    failed = [t for t in themes if "既存承認済み失敗テーマ" in t["theme"]]
    assert len(failed) == 1
    assert failed[0]["status"] == "approved"
    job = failed[0].get("latest_job")
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] is not None


def test_main_reuses_existing_approved_theme(tmp_path: Path):
    output_dir = tmp_path / "research3"

    with (
        patch.object(runner, "collect_research_context", return_value=""),
        patch.object(runner, "route_research_topic", return_value="internal"),
        patch.object(runner.llm_client, "generate_llm_response", return_value="mocked"),
        patch.object(runner, "conduct_research", return_value="report1"),
        patch.object(runner.config, "RESEARCH_OUTPUT_DIR", output_dir),
    ):
        result1 = runner.main(theme="再利用テーマ")
        assert result1.success_count == 1

    themes1 = research_themes.list_themes()
    themes1 = [t for t in themes1 if "再利用テーマ" in t["theme"]]
    assert len(themes1) == 1
    first_id = themes1[0]["theme_id"]

    with (
        patch.object(runner, "collect_research_context", return_value=""),
        patch.object(runner, "route_research_topic", return_value="internal"),
        patch.object(
            runner.llm_client, "generate_llm_response", return_value="mocked_v2"
        ),
        patch.object(runner, "conduct_research", return_value="report2"),
        patch.object(runner.config, "RESEARCH_OUTPUT_DIR", output_dir),
    ):
        result2 = runner.main(theme="再利用テーマ")
        assert result2.success_count == 1

    themes2 = research_themes.list_themes()
    themes2 = [t for t in themes2 if "再利用テーマ" in t["theme"]]
    assert len(themes2) == 1
    assert themes2[0]["theme_id"] == first_id


def test_gpt_researcher_environment_uses_config_and_restores_prior_values(monkeypatch):
    monkeypatch.setenv("FAST_LLM", "original-fast")
    monkeypatch.delenv("SMART_LLM", raising=False)

    with (
        patch.object(
            runner.config, "RESEARCH_GPT_RESEARCHER_FAST_LLM", "configured-fast"
        ),
        patch.object(
            runner.config, "RESEARCH_GPT_RESEARCHER_SMART_LLM", "configured-smart"
        ),
    ):
        with runner._gpt_researcher_environment():
            assert os.environ["FAST_LLM"] == "configured-fast"
            assert os.environ["SMART_LLM"] == "configured-smart"

    assert os.environ["FAST_LLM"] == "original-fast"
    assert "SMART_LLM" not in os.environ


def test_normalize_project_mode_and_alias():
    assert runner._normalize_research_mode("project") == runner.RESEARCH_MODE_PROJECT
    assert runner._normalize_research_mode("coding") == runner.RESEARCH_MODE_PROJECT
    assert runner._normalize_research_mode("codebase") == runner.RESEARCH_MODE_PROJECT


def test_project_mode_requires_project_id():
    with pytest.raises(ValueError, match="project_id"):
        runner.run_research(theme="PJ調査", mode="project")


def test_auto_mode_with_project_id_uses_project_engine():
    with (
        patch.object(runner, "collect_research_context", return_value=""),
        patch.object(runner, "_resolve_project_label", return_value="Proj (path)"),
        patch.object(runner, "generate_research_title", return_value="title"),
        patch.object(runner, "build_research_prompt", return_value="prompt") as build,
        patch.object(runner, "conduct_research", return_value="report") as conduct,
    ):
        report = runner.run_research(theme="PJ調査", mode="auto", project_id=7)

    assert report.mode == runner.RESEARCH_MODE_PROJECT
    assert build.call_args.kwargs["project_label"] == "Proj (path)"
    assert conduct.call_args.kwargs["project_id"] == 7


def test_project_id_persisted_on_theme_and_job():
    theme = research_themes.create_theme(theme="PJ永続化", project_id=12)
    assert theme["project_id"] == 12

    job = research_themes.create_job(theme["theme_id"], project_id=12)
    assert job["project_id"] == 12

    fetched = research_themes.get_theme(theme["theme_id"])
    assert fetched["project_id"] == 12

    listed = [
        t for t in research_themes.list_themes() if t["theme_id"] == theme["theme_id"]
    ]
    assert listed[0]["latest_job"]["project_id"] == 12


def test_approved_theme_not_reused_across_projects():
    existing = research_themes.create_theme(
        theme="PJ跨ぎ再利用", status="approved", project_id=1
    )
    theme_rec, job_rec = runner.get_or_create_theme_and_job(
        theme="PJ跨ぎ再利用", project_id=2
    )

    assert theme_rec["theme_id"] != existing["theme_id"]
    assert theme_rec["project_id"] == 2
    assert job_rec["project_id"] == 2
    assert theme_rec["latest_job"]["project_id"] == 2
