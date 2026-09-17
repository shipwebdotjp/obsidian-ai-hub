"""Isolation scenario for project-grounded research.

The coding agent must never modify the project's primary working tree: it runs
inside a disposable detached worktree that is removed after the turn. These
tests pin that operation-scenario contract.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from obsidian_ai_hub.coding.acp import AcpClientBackend, AcpExecutionResult
from obsidian_ai_hub.research import coding_research
from obsidian_ai_hub.research.coding_research import (
    CodingResearchError,
    run_project_research_report,
)


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], path)
    _git(["config", "user.email", "test@example.com"], path)
    _git(["config", "user.name", "Test"], path)
    (path / "README.md").write_text("hello", encoding="utf-8")
    _git(["add", "."], path)
    _git(["commit", "-q", "-m", "init"], path)
    return path


def test_project_research_runs_in_disposable_worktree(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    head_before = _git(["rev-parse", "HEAD"], repo)
    seen_repo_paths: list[Path] = []

    def fake_execute(self, *, repo_path, prompt, **kwargs):
        seen_repo_paths.append(Path(repo_path))
        (Path(repo_path) / "agent_scratch.txt").write_text("temp", encoding="utf-8")
        return AcpExecutionResult(
            acp_session_id="s1", output="# report\nbody", exit_code=0
        )

    with (
        patch.object(
            coding_research,
            "_resolve_project_repo",
            return_value=(str(repo), "repo"),
        ),
        patch.object(AcpClientBackend, "execute_turn", fake_execute),
    ):
        report = run_project_research_report("prompt", project_id=1)

    assert report == "# report\nbody"

    agent_repo = seen_repo_paths[0]
    assert agent_repo != repo
    assert not agent_repo.exists()

    assert _git(["rev-parse", "HEAD"], repo) == head_before
    assert _git(["status", "--porcelain"], repo) == ""
    assert not (repo / "agent_scratch.txt").exists()

    worktrees = _git(["worktree", "list", "--porcelain"], repo)
    assert worktrees.count("worktree ") == 1


def test_project_research_propagates_agent_error(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")

    def fake_execute(self, *, repo_path, prompt, **kwargs):
        return AcpExecutionResult(
            acp_session_id="s1", output="", exit_code=1, error_message="boom"
        )

    with (
        patch.object(
            coding_research,
            "_resolve_project_repo",
            return_value=(str(repo), "repo"),
        ),
        patch.object(AcpClientBackend, "execute_turn", fake_execute),
    ):
        with pytest.raises(CodingResearchError, match="boom"):
            run_project_research_report("prompt", project_id=1)

    assert _git(["status", "--porcelain"], repo) == ""


def test_project_research_rejects_empty_report(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")

    def fake_execute(self, *, repo_path, prompt, **kwargs):
        return AcpExecutionResult(acp_session_id="s1", output="   ", exit_code=0)

    with (
        patch.object(
            coding_research,
            "_resolve_project_repo",
            return_value=(str(repo), "repo"),
        ),
        patch.object(AcpClientBackend, "execute_turn", fake_execute),
    ):
        with pytest.raises(CodingResearchError, match="empty report"):
            run_project_research_report("prompt", project_id=1)


def test_resolve_project_repo_requires_configured_path(monkeypatch):
    monkeypatch.setattr(
        "obsidian_ai_hub.web.services.projects.get_project_detail",
        lambda project_id: {"display_name": "P", "project_path": None},
    )
    with pytest.raises(CodingResearchError, match="project_path"):
        coding_research._resolve_project_repo(1)


def test_resolve_project_repo_missing_project(monkeypatch):
    monkeypatch.setattr(
        "obsidian_ai_hub.web.services.projects.get_project_detail",
        lambda project_id: None,
    )
    with pytest.raises(CodingResearchError, match="not found"):
        coding_research._resolve_project_repo(1)
