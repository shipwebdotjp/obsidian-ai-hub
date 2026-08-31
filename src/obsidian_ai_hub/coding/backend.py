"""CLI Backend adapters for Codex CLI and OpenCode CLI."""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from obsidian_ai_hub.utils.config import (
    CODING_CODEX_CLI_PATH,
    CODING_OPENCODE_CLI_PATH,
)

logger = logging.getLogger(__name__)


@dataclass
class CodingBackendResult:
    external_session_id: str
    output: str
    exit_code: int
    error_message: Optional[str] = None
    cancelled: bool = False


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
        raise ValueError(f"Path '{repo_path}' is not a valid Git repository root") from exc


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


class CodingBackend(ABC):
    """Abstract interface for CLI coding execution backends."""

    @abstractmethod
    def execute(
        self,
        repo_path: str,
        prompt: str,
        external_session_id: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout: int = 600,
    ) -> CodingBackendResult:
        """Execute CLI command inside repo_path."""
        pass


class _BaseSubprocessBackend(CodingBackend):
    """Common helper for subprocess execution with cancel/timeout support."""

    def _run_subprocess(
        self,
        argv: list[str],
        cwd: str,
        cancel_event: Optional[threading.Event] = None,
        timeout: int = 600,
    ) -> tuple[int, str, str, bool]:
        """Run process with group signal termination on cancel/timeout.

        Returns (exit_code, stdout, stderr, cancelled).
        """
        env = os.environ.copy()
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        cancelled = False

        def read_pipe(pipe, container):
            try:
                for line in iter(pipe.readline, ""):
                    container.append(line)
            except Exception as exc:
                logger.warning("Error reading subprocess pipe: %s", exc)
            finally:
                pipe.close()

        t_out = threading.Thread(target=read_pipe, args=(proc.stdout, stdout_chunks))
        t_err = threading.Thread(target=read_pipe, args=(proc.stderr, stderr_chunks))
        t_out.daemon = True
        t_err.daemon = True
        t_out.start()
        t_err.start()

        start_time = time.monotonic()
        poll_interval = 0.2

        while proc.poll() is None:
            if cancel_event and cancel_event.is_set():
                cancelled = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break

            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                cancelled = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break

            if cancel_event:
                cancel_event_triggered = cancel_event.wait(poll_interval)
                if cancel_event_triggered:
                    cancelled = True
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    break
            else:
                time.sleep(poll_interval)

        proc.wait()
        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)

        stdout_str = "".join(stdout_chunks).strip()
        stderr_str = "".join(stderr_chunks).strip()
        return proc.returncode, stdout_str, stderr_str, cancelled


class CodexCliBackend(_BaseSubprocessBackend):
    """Codex CLI backend adapter."""

    def execute(
        self,
        repo_path: str,
        prompt: str,
        external_session_id: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout: int = 600,
    ) -> CodingBackendResult:
        exe_path = CODING_CODEX_CLI_PATH or "codex"
        argv = [exe_path]

        sess_id = external_session_id or f"codex_sess_{uuid.uuid4().hex[:12]}"

        if external_session_id:
            argv.extend(["--session", external_session_id])
        else:
            argv.extend(["--session", sess_id])

        argv.extend(["exec", prompt])

        try:
            exit_code, stdout, stderr, cancelled = self._run_subprocess(
                argv, cwd=repo_path, cancel_event=cancel_event, timeout=timeout
            )
        except Exception as exc:
            logger.exception("Failed to execute Codex CLI")
            return CodingBackendResult(
                external_session_id=sess_id,
                output="",
                exit_code=-1,
                error_message=str(exc),
                cancelled=False,
            )

        if cancelled:
            return CodingBackendResult(
                external_session_id=sess_id,
                output=stdout,
                exit_code=exit_code,
                error_message="Cancelled by user or timed out",
                cancelled=True,
            )

        # Extract session ID if printed in stdout/stderr if different
        m = re.search(r"session[_-]?id[:=]\s*([a-zA-Z0-9_-]+)", stdout + stderr)
        if m:
            sess_id = m.group(1)

        output = stdout if stdout else stderr
        err_msg = None if exit_code == 0 else (stderr or f"Exit code {exit_code}")

        return CodingBackendResult(
            external_session_id=sess_id,
            output=output,
            exit_code=exit_code,
            error_message=err_msg,
            cancelled=False,
        )


class OpenCodeCliBackend(_BaseSubprocessBackend):
    """OpenCode CLI backend adapter."""

    def execute(
        self,
        repo_path: str,
        prompt: str,
        external_session_id: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout: int = 600,
    ) -> CodingBackendResult:
        exe_path = CODING_OPENCODE_CLI_PATH or "opencode"
        argv = [exe_path]

        sess_id = external_session_id or f"opencode_sess_{uuid.uuid4().hex[:12]}"

        if external_session_id:
            argv.extend(["--session", external_session_id])
        else:
            argv.extend(["--session", sess_id])

        argv.extend(["run", prompt])

        try:
            exit_code, stdout, stderr, cancelled = self._run_subprocess(
                argv, cwd=repo_path, cancel_event=cancel_event, timeout=timeout
            )
        except Exception as exc:
            logger.exception("Failed to execute OpenCode CLI")
            return CodingBackendResult(
                external_session_id=sess_id,
                output="",
                exit_code=-1,
                error_message=str(exc),
                cancelled=False,
            )

        if cancelled:
            return CodingBackendResult(
                external_session_id=sess_id,
                output=stdout,
                exit_code=exit_code,
                error_message="Cancelled by user or timed out",
                cancelled=True,
            )

        m = re.search(r"session[_-]?id[:=]\s*([a-zA-Z0-9_-]+)", stdout + stderr)
        if m:
            sess_id = m.group(1)

        output = stdout if stdout else stderr
        err_msg = None if exit_code == 0 else (stderr or f"Exit code {exit_code}")

        return CodingBackendResult(
            external_session_id=sess_id,
            output=output,
            exit_code=exit_code,
            error_message=err_msg,
            cancelled=False,
        )


def get_backend(backend_type: str) -> CodingBackend:
    """Get coding backend adapter instance by type name."""
    b_type = (backend_type or "").lower().strip()
    if b_type == "codex":
        return CodexCliBackend()
    elif b_type == "opencode":
        return OpenCodeCliBackend()
    else:
        raise ValueError(f"Unknown coding backend type: '{backend_type}' (expected 'codex' or 'opencode')")
