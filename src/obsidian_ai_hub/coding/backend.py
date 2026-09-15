"""Git helpers for the Coding Workspace (ACP-only, OpenCode only).

Direct CLI backends (CodexCliBackend / OpenCodeCliBackend) were removed
when the workspace was unified on the ACP transport. This module keeps
only repository validation and status helpers shared by the service,
worker, and web layers.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_git_repo(repo_path: str | Path) -> str:
    """Validate that repo_path is an existing directory and a Git repository root.

    Returns the canonical Git root path string. Raises ValueError if invalid.
    """
    path = Path(repo_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Path '{repo_path}' does not exist")
    if not path.is_dir():
        raise ValueError(f"Path '{repo_path}' is not a directory")

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )
        git_root = Path(proc.stdout.strip()).resolve()
        return str(git_root)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ValueError(
            f"Path '{repo_path}' is not a valid Git repository root"
        ) from exc


def check_dirty_tree(repo_path: str | Path) -> tuple[bool, str]:
    """Check for uncommitted changes using git status --porcelain=v1.

    Returns (is_dirty, status_output).
    """
    path = Path(repo_path).expanduser().resolve()
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )
        output = proc.stdout.strip()
        return bool(output), output
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("Failed to run git status on '%s': %s", repo_path, exc)
        return False, ""


def get_git_status(repo_path: str | Path) -> dict:
    """Get Git status information (branch, ahead/behind counts, diff line counts).

    Returns dict with keys: branch, ahead, behind, insertions, deletions.
    """
    path = Path(repo_path).expanduser().resolve()
    branch = ""
    ahead = 0
    behind = 0
    insertions = 0
    deletions = 0

    # 1. Branch name
    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )
        branch = proc.stdout.strip()
        if not branch:
            # Fallback to commit SHA / HEAD description if detached
            rev_proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=path,
                capture_output=True,
                text=True,
            )
            if rev_proc.returncode == 0:
                branch = rev_proc.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        logger.warning("Failed to get git branch for '%s': %s", repo_path, exc)

    # 2. Ahead / Behind counts against upstream branch
    try:
        proc = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            parts = proc.stdout.strip().split()
            if len(parts) == 2:
                behind = int(parts[0])
                ahead = int(parts[1])
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        logger.debug("Failed to get ahead/behind count for '%s': %s", repo_path, exc)

    # 3. Diff line counts (insertions / deletions) across staged and unstaged changes
    try:
        proc = subprocess.run(
            ["git", "diff", "HEAD", "--numstat"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            proc = subprocess.run(
                ["git", "diff", "--numstat"],
                cwd=path,
                capture_output=True,
                text=True,
            )

        if proc.returncode == 0 and proc.stdout.strip():
            for line in proc.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    ins_str, del_str = parts[0], parts[1]
                    if ins_str.isdigit():
                        insertions += int(ins_str)
                    if del_str.isdigit():
                        deletions += int(del_str)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        logger.warning("Failed to get git diff numstat for '%s': %s", repo_path, exc)

    return {
        "branch": branch,
        "ahead": ahead,
        "behind": behind,
        "insertions": insertions,
        "deletions": deletions,
    }
