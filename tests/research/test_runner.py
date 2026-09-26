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
        patch.object(
            runner, "route_research_topic", return_value=runner.ResearchRouteDecision(mode="internal")
        ),
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
        patch.object(
            runner, "route_research_topic", return_value=runner.ResearchRouteDecision(mode="internal")
        ),
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
        patch.object(
            runner, "route_research_topic", return_value=runner.ResearchRouteDecision(mode="internal")
        ),
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
        patch.object(
            runner, "route_research_topic", return_value=runner.ResearchRouteDecision(mode="internal")
        ),
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
        patch.object(
            runner, "route_research_topic", return_value=runner.ResearchRouteDecision(mode="internal")
        ),
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
        patch.object(
            runner, "route_research_topic", return_value=runner.ResearchRouteDecision(mode="internal")
        ),
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
        patch.object(
            runner, "route_research_topic", return_value=runner.ResearchRouteDecision(mode="internal")
        ),
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
        patch.object(
            runner, "route_research_topic", return_value=runner.ResearchRouteDecision(mode="internal")
        ),
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


def _stub_report_pipeline(monkeypatch, captured: dict | None = None):
    monkeypatch.setattr(runner, "collect_research_context", lambda theme, ctx=None: "")
    monkeypatch.setattr(runner, "build_research_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(runner, "generate_research_title", lambda theme: "title")

    def fake_conduct(prompt, *, mode, output_style=None, project_id=None):
        if captured is not None:
            captured["mode"] = mode
            captured["project_id"] = project_id
        return "report"

    monkeypatch.setattr(runner, "conduct_research", fake_conduct)


def test_list_project_router_candidates_filters_invalid_git(monkeypatch):
    projects = [
        {
            "project_id": 1,
            "display_name": "Obsidian AI Hub",
            "goal": "goal",
            "description": "desc",
            "keywords": ["ai", "obsidian"],
            "project_path": "/repo/a",
        },
        {"project_id": 2, "display_name": "B", "project_path": "/repo/b"},
        {"project_id": 3, "display_name": "C", "project_path": None},
    ]
    monkeypatch.setattr(
        "obsidian_ai_hub.web.services.projects.list_projects", lambda: projects
    )

    def fake_validate(path):
        if path == "/repo/b":
            raise ValueError("not a repo")
        return path

    monkeypatch.setattr(
        "obsidian_ai_hub.coding.backend.validate_git_repo", fake_validate
    )

    candidates = runner._list_project_router_candidates()
    assert [c["project_id"] for c in candidates] == [1]
    assert candidates[0]["keywords"] == ["ai", "obsidian"]
    assert "project_path" not in candidates[0]


def test_parse_router_response_structured_and_legacy():
    ids = {7}
    decision = runner._parse_router_response(
        '{"mode": "project", "project_id": 7, "confidence": 0.9}', ids
    )
    assert decision is not None
    assert decision.mode == runner.RESEARCH_MODE_PROJECT
    assert decision.project_id == 7

    assert (
        runner._parse_router_response(
            '{"mode": "project", "project_id": 99, "confidence": 0.9}', ids
        )
        is None
    )
    assert (
        runner._parse_router_response(
            '{"mode": "project", "project_id": 7, "confidence": 0.5}', ids
        )
        is None
    )
    assert runner._parse_router_response('{"mode": "banana"}', ids) is None

    # Non-integral / boolean ids and non-finite confidences must not be coerced.
    assert (
        runner._parse_router_response(
            '{"mode": "project", "project_id": 7.9, "confidence": 0.9}', ids
        )
        is None
    )
    assert (
        runner._parse_router_response(
            '{"mode": "project", "project_id": true, "confidence": 0.9}', ids
        )
        is None
    )
    assert (
        runner._parse_router_response(
            '{"mode": "project", "project_id": 7, "confidence": NaN}', ids
        )
        is None
    )
    assert (
        runner._parse_router_response(
            '{"mode": "project", "project_id": 7, "confidence": Infinity}', ids
        )
        is None
    )

    fenced = runner._parse_router_response('```json\n{"mode": "web"}\n```', ids)
    assert fenced is not None
    assert fenced.mode == runner.RESEARCH_MODE_WEB

    legacy = runner._parse_router_response("deep", ids)
    assert legacy is not None
    assert legacy.mode == runner.RESEARCH_MODE_DEEP

    assert runner._parse_router_response("???", ids) is None


def test_route_research_topic_passes_direction_and_projects(monkeypatch):
    captured: dict = {}

    def fake_render(path, context):
        captured.update(context)
        return "prompt"

    monkeypatch.setattr(runner.prompt, "render_prompt", fake_render)
    monkeypatch.setattr(
        runner,
        "_list_project_router_candidates",
        lambda: [
            {
                "project_id": 7,
                "name": "Obsidian AI Hub",
                "goal": "goal",
                "description": "desc",
                "keywords": ["ai"],
            }
        ],
    )
    monkeypatch.setattr(
        runner.llm_client,
        "generate_llm_response",
        lambda **kwargs: '{"mode": "project", "project_id": 7, "confidence": 0.91}',
    )

    decision = runner.route_research_topic("theme", why_now="why", direction="dir")

    assert decision.mode == runner.RESEARCH_MODE_PROJECT
    assert decision.project_id == 7
    assert "Obsidian AI Hub" in captured["projects_text"]
    assert captured["direction_text"] == "dir"
    assert captured["why_now_text"] == "why"
    assert captured["theme"] == "theme"
    # Collected context is never supplied to the router; compat value stays empty.
    assert captured["context_text"] == ""
    assert "ctx" not in str(captured.values())


def test_route_research_topic_has_no_context_param():
    import inspect

    params = inspect.signature(runner.route_research_topic).parameters
    assert "context" not in params
    router_params = inspect.signature(runner.build_web_research_router_prompt).parameters
    assert "context" not in router_params


def test_resolve_route_collects_context_after_routing(monkeypatch):
    calls: list[str] = []
    captured_router: dict = {}
    captured_prompt: dict = {}

    def fake_router(theme, *, why_now=None, direction=None):
        calls.append("route")
        captured_router["theme"] = theme
        captured_router["why_now"] = why_now
        captured_router["direction"] = direction
        assert "context" not in captured_router
        return runner.ResearchRouteDecision(mode=runner.RESEARCH_MODE_INTERNAL)

    def fake_collect(theme, explicit_context=None):
        calls.append("collect")
        assert explicit_context == "approval comment"
        return "collected-context"

    def fake_build(theme, *, mode, context=None, **kwargs):
        captured_prompt["context"] = context
        return "final-prompt"

    monkeypatch.setattr(runner, "route_research_topic", fake_router)
    monkeypatch.setattr(runner, "collect_research_context", fake_collect)
    monkeypatch.setattr(runner, "build_research_prompt", fake_build)
    monkeypatch.setattr(runner, "generate_research_title", lambda theme: "title")
    monkeypatch.setattr(runner, "conduct_research", lambda *a, **k: "report")

    route = runner.resolve_research_route(
        "theme",
        direction="dir",
        why_now="why",
        mode="auto",
        context="approval comment",
    )

    assert calls == ["route", "collect"]
    assert captured_router == {"theme": "theme", "why_now": "why", "direction": "dir"}
    assert route.context == "collected-context"

    report = runner.run_research(
        theme="theme",
        direction="dir",
        why_now="why",
        mode="auto",
        context="approval comment",
    )
    assert captured_prompt["context"] == "collected-context"
    assert report.markdown.startswith("---\ntitle: title")


def test_generate_title_uses_theme_only(monkeypatch):
    import inspect

    assert "expanded_prompt" not in inspect.signature(
        runner.generate_research_title
    ).parameters
    assert "expanded_prompt" not in inspect.signature(
        runner.build_title_prompt
    ).parameters

    captured: dict = {}

    def fake_render(path, context):
        captured.update(context)
        return "title-prompt"

    monkeypatch.setattr(runner.prompt, "render_prompt", fake_render)
    monkeypatch.setattr(
        runner.llm_client, "generate_llm_response", lambda **kwargs: "  title  "
    )

    assert runner.generate_research_title("my theme") == "title"
    assert captured["theme"] == "my theme"
    assert captured["expanded_prompt"] == ""
    assert captured["context_text"] == ""


def test_title_prompt_compat_empty_values_for_custom_templates(tmp_path, monkeypatch):
    custom = tmp_path / "custom_title.md"
    custom.write_text("T:${theme} E:${expanded_prompt} C:${context_text}", encoding="utf-8")
    monkeypatch.setattr(runner.config, "RESEARCH_TITLE_PROMPT_PATH", custom)
    assert runner.build_title_prompt("theme-only") == "T:theme-only E: C:"


def test_router_prompt_compat_empty_values_for_custom_templates(tmp_path, monkeypatch):
    custom = tmp_path / "custom_router.md"
    custom.write_text(
        "T:${theme} D:${direction_text} W:${why_now_text} C:${context_text}",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner.config, "RESEARCH_ROUTER_PROMPT_PATH", custom)
    rendered = runner.build_web_research_router_prompt(
        "theme", why_now="why", direction="dir", projects_text="proj"
    )
    assert rendered == "T:theme D:dir W:why C:"


def test_route_research_topic_unknown_project_falls_back_to_internal(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_list_project_router_candidates",
        lambda: [{"project_id": 7, "name": "P", "keywords": []}],
    )
    monkeypatch.setattr(
        runner, "build_web_research_router_prompt", lambda *a, **k: "prompt"
    )
    monkeypatch.setattr(
        runner.llm_client,
        "generate_llm_response",
        lambda **kwargs: '{"mode": "project", "project_id": 99, "confidence": 0.99}',
    )

    decision = runner.route_research_topic("theme")

    assert decision.mode == runner.RESEARCH_MODE_INTERNAL
    assert decision.project_id is None


def test_route_research_topic_legacy_response_is_used(monkeypatch):
    monkeypatch.setattr(runner, "_list_project_router_candidates", lambda: [])
    monkeypatch.setattr(
        runner, "build_web_research_router_prompt", lambda *a, **k: "prompt"
    )
    monkeypatch.setattr(
        runner.llm_client, "generate_llm_response", lambda **kwargs: "web"
    )

    assert runner.route_research_topic("theme").mode == runner.RESEARCH_MODE_WEB


def test_explicit_project_mode_skips_router(monkeypatch):
    router_called = {"value": False}

    def fake_router(*args, **kwargs):
        router_called["value"] = True
        return runner.ResearchRouteDecision(mode=runner.RESEARCH_MODE_INTERNAL)

    _stub_report_pipeline(monkeypatch)
    monkeypatch.setattr(runner, "route_research_topic", fake_router)
    monkeypatch.setattr(runner, "_resolve_project_label", lambda pid: "P")

    report = runner.run_research(theme="PJ", mode="project", project_id=3)

    assert report.mode == runner.RESEARCH_MODE_PROJECT
    assert router_called["value"] is False


def test_auto_mode_with_existing_project_id_skips_router(monkeypatch):
    router_called = {"value": False}

    def fake_router(*args, **kwargs):
        router_called["value"] = True
        return runner.ResearchRouteDecision(mode=runner.RESEARCH_MODE_INTERNAL)

    _stub_report_pipeline(monkeypatch)
    monkeypatch.setattr(runner, "route_research_topic", fake_router)
    monkeypatch.setattr(runner, "_resolve_project_label", lambda pid: "P")

    report = runner.run_research(theme="PJ", mode="auto", project_id=4)

    assert report.mode == runner.RESEARCH_MODE_PROJECT
    assert router_called["value"] is False


def test_execute_job_auto_project_persists_before_project_research(
    monkeypatch, tmp_path: Path
):
    theme = research_themes.create_theme(theme="縦断PJ", kind="explore", confidence=0.8)
    job = research_themes.create_job(theme["theme_id"])

    _stub_report_pipeline(monkeypatch)
    monkeypatch.setattr(
        runner,
        "route_research_topic",
        lambda *a, **k: runner.ResearchRouteDecision(
            mode=runner.RESEARCH_MODE_PROJECT, project_id=7, confidence=0.9
        ),
    )
    monkeypatch.setattr(runner, "_resolve_project_label", lambda pid: "Obsidian AI Hub")

    captured: dict = {}

    def fake_conduct(prompt, *, mode, output_style=None, project_id=None):
        captured["project_id"] = project_id
        return "report"

    monkeypatch.setattr(runner, "conduct_research", fake_conduct)

    result = runner.execute_research_job_sync(
        theme["theme_id"], job["job_id"], mode="auto"
    )

    assert result["status"] == "succeeded"
    assert captured["project_id"] == 7
    assert result["output_path"] is not None
    assert research_themes.get_theme(theme["theme_id"])["project_id"] == 7
    assert research_themes.get_job(job["job_id"])["project_id"] == 7


def test_execute_job_project_failure_does_not_save_vault(monkeypatch):
    from obsidian_ai_hub.research.coding_research import CodingResearchError

    theme = research_themes.create_theme(
        theme="縦断PJ失敗", kind="explore", confidence=0.8
    )
    job = research_themes.create_job(theme["theme_id"])

    _stub_report_pipeline(monkeypatch)
    monkeypatch.setattr(
        runner,
        "route_research_topic",
        lambda *a, **k: runner.ResearchRouteDecision(
            mode=runner.RESEARCH_MODE_PROJECT, project_id=7, confidence=0.9
        ),
    )
    monkeypatch.setattr(runner, "_resolve_project_label", lambda pid: "Obsidian AI Hub")

    def boom(*args, **kwargs):
        raise CodingResearchError("agent boom")

    monkeypatch.setattr(runner, "conduct_research", boom)

    result = runner.execute_research_job_sync(
        theme["theme_id"], job["job_id"], mode="auto"
    )

    assert result["status"] == "failed"
    assert result["output_path"] is None
    assert research_themes.get_theme(theme["theme_id"])["status"] == "candidate"
    # The selected project is persisted before the coding agent is started.
    assert research_themes.get_theme(theme["theme_id"])["project_id"] == 7
    assert research_themes.get_job(job["job_id"])["project_id"] == 7
