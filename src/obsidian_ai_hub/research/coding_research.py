"""Project-grounded research executed through the OpenCode ACP coding agent.

The coding agent is started with its process cwd inside a temporary detached
Git worktree, so ordinary relative writes land in the disposable worktree and
are discarded when the turn finishes. This is best-effort isolation, not a
filesystem sandbox: the agent inherits full filesystem access and could still
write outside the worktree through absolute paths or traversal.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from obsidian_ai_hub.coding.backend import validate_git_repo

logger = logging.getLogger(__name__)

WORKTREE_TMP_PREFIX = "research-project-"


class CodingResearchError(RuntimeError):
    """Raised when project-grounded research cannot be completed."""


def _git(args: list[str], cwd: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise CodingResearchError(f"git {' '.join(args)} failed: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise CodingResearchError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout.strip()


@contextmanager
def _temporary_worktree(repo_root: str) -> Iterator[str]:
    tmp_parent = tempfile.mkdtemp(prefix=WORKTREE_TMP_PREFIX)
    worktree_path = str(Path(tmp_parent) / "repo")
    created = False
    try:
        _git(["worktree", "add", "--detach", worktree_path, "HEAD"], repo_root)
        created = True
        yield worktree_path
    finally:
        if created:
            try:
                _git(["worktree", "remove", "--force", worktree_path], repo_root)
            except Exception:
                logger.exception(
                    "Failed to remove project research worktree %s", worktree_path
                )
        shutil.rmtree(tmp_parent, ignore_errors=True)
        try:
            _git(["worktree", "prune"], repo_root)
        except Exception:
            logger.warning("Failed to prune project research worktrees in %s", repo_root)


def _resolve_project_repo(project_id: int) -> tuple[str, str]:
    from obsidian_ai_hub.web.services.projects import get_project_detail

    try:
        resolved_project_id = int(project_id)
    except (TypeError, ValueError) as exc:
        raise CodingResearchError(f"invalid project id: {project_id!r}") from exc
    project = get_project_detail(resolved_project_id)
    if not project:
        raise CodingResearchError(f"project {project_id} was not found")
    project_path = project.get("project_path")
    if not project_path:
        raise CodingResearchError(
            f"project {project_id} has no project_path configured"
        )
    try:
        repo_root = validate_git_repo(project_path)
    except ValueError as exc:
        raise CodingResearchError(str(exc)) from exc
    label = (
        project.get("display_name")
        or project.get("normalized_name")
        or str(project_id)
    )
    return repo_root, label


def run_project_research_report(
    prompt: str,
    *,
    project_id: int,
    timeout: Optional[float] = None,
) -> str:
    from obsidian_ai_hub.coding.acp import (
        DEFAULT_ACP_TURN_TIMEOUT_S,
        AcpClientBackend,
        AcpLaunchProfile,
    )

    repo_root, label = _resolve_project_repo(project_id)
    backend = AcpClientBackend(AcpLaunchProfile.get_profile("opencode"))
    logger.info(
        "Running project research for project %s (%s) in a temporary worktree",
        project_id,
        label,
    )
    with _temporary_worktree(repo_root) as worktree:
        result = backend.execute_turn(
            repo_path=worktree,
            prompt=prompt,
            timeout=timeout if timeout is not None else DEFAULT_ACP_TURN_TIMEOUT_S,
        )
    if result.error_message:
        raise CodingResearchError(result.error_message)
    report = (result.output or "").strip()
    if not report:
        raise CodingResearchError("coding agent returned an empty report")
    return report
