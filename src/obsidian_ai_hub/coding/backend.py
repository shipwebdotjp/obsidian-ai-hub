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
    external_session_id: Optional[str]
    output: str
    exit_code: int
    error_message: Optional[str] = None
    cancelled: bool = False
    session_recreated: bool = False


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

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Strip ANSI escape sequences from text."""
        ansi_regex = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        return ansi_regex.sub("", text)

    @staticmethod
    def _parse_codex_json_output(
        stdout: str, stderr: str
    ) -> tuple[Optional[str], str, Optional[str]]:
        """Parse Codex CLI JSON Lines output.

        Extracts thread ID (from thread.started event) and agent_message text
        (from item.completed events).
        Returns (thread_id, agent_message_text, json_error_message).
        """
        import json

        extracted_thread_id = None
        agent_messages: list[str] = []
        json_errors: list[str] = []

        combined = stdout + "\n" + stderr if stderr else stdout
        for line in combined.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    data = json.loads(line_str)
                    if isinstance(data, dict):
                        event_type = data.get("type")

                        # 1. Thread ID extraction
                        if event_type == "thread.started":
                            if "thread_id" in data and isinstance(data["thread_id"], str):
                                extracted_thread_id = data["thread_id"]
                            elif "thread" in data and isinstance(data["thread"], dict):
                                thread_obj = data["thread"]
                                if "id" in thread_obj and isinstance(thread_obj["id"], str):
                                    extracted_thread_id = thread_obj["id"]

                        # Fallback for thread_id if present in top level
                        if not extracted_thread_id and "thread_id" in data and isinstance(data["thread_id"], str):
                            extracted_thread_id = data["thread_id"]

                        # 2. Agent message extraction
                        if event_type == "item.completed":
                            item = data.get("item")
                            if isinstance(item, dict):
                                item_type = item.get("type")
                                if item_type == "agent_message":
                                    txt = item.get("text")
                                    if isinstance(txt, str) and txt:
                                        agent_messages.append(txt)
                                elif "agent_message" in item and isinstance(item["agent_message"], dict):
                                    msg_obj = item["agent_message"]
                                    txt = msg_obj.get("text")
                                    if isinstance(txt, str) and txt:
                                        agent_messages.append(txt)

                        # 3. JSON Error event extraction
                        if event_type == "error":
                            msg = data.get("message") or data.get("error")
                            if isinstance(msg, str) and msg:
                                json_errors.append(msg)
                        elif "error" in data and isinstance(data["error"], str) and data["error"]:
                            json_errors.append(data["error"])

                except json.JSONDecodeError:
                    pass

        # Return the last non-empty agent_message as final output, or fallback to stdout/stderr
        output_text = agent_messages[-1] if agent_messages else (stdout.strip() or stderr.strip())
        json_error_msg = "\n".join(json_errors).strip() if json_errors else None

        return extracted_thread_id, output_text, json_error_msg

    def execute(
        self,
        repo_path: str,
        prompt: str,
        external_session_id: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout: int = 600,
    ) -> CodingBackendResult:
        exe_path = CODING_CODEX_CLI_PATH or "codex"

        def _run_cmd(thread_id_opt: Optional[str]):
            argv = [exe_path, "exec"]
            if thread_id_opt:
                argv.extend(["resume", "--json", thread_id_opt, prompt])
            else:
                argv.extend(["--json", "--sandbox", "workspace-write", prompt])
            return self._run_subprocess(
                argv, cwd=repo_path, cancel_event=cancel_event, timeout=timeout
            )

        try:
            exit_code, stdout, stderr, cancelled = _run_cmd(external_session_id)
        except Exception as exc:
            logger.exception("Failed to execute Codex CLI")
            return CodingBackendResult(
                external_session_id=external_session_id,
                output="",
                exit_code=-1,
                error_message=str(exc),
                cancelled=False,
            )

        extracted_thread_id, parsed_text, json_err = self._parse_codex_json_output(stdout, stderr)
        current_thread_id = extracted_thread_id or external_session_id

        if cancelled:
            return CodingBackendResult(
                external_session_id=current_thread_id,
                output=parsed_text,
                exit_code=exit_code,
                error_message="Cancelled by user or timed out",
                cancelled=True,
            )

        clean_combined = self._strip_ansi(stdout + "\n" + stderr + "\n" + (json_err or ""))

        # Check for Session not found or thread not found when external_session_id was provided
        if external_session_id and (
            "session not found" in clean_combined.lower()
            or "thread not found" in clean_combined.lower()
        ):
            logger.warning(
                "Codex thread '%s' not found. Retrying once with a new thread...",
                external_session_id,
            )
            try:
                r_exit, r_stdout, r_stderr, r_cancelled = _run_cmd(None)
            except Exception as exc:
                logger.exception("Failed during Codex retry execution")
                return CodingBackendResult(
                    external_session_id=None,
                    output="",
                    exit_code=-1,
                    error_message=f"Retry failed: {str(exc)}",
                    cancelled=False,
                    session_recreated=False,
                )

            r_thread_id, r_text, r_json_err = self._parse_codex_json_output(r_stdout, r_stderr)

            if r_cancelled:
                return CodingBackendResult(
                    external_session_id=None,
                    output=r_text,
                    exit_code=r_exit,
                    error_message="Cancelled by user or timed out during retry",
                    cancelled=True,
                    session_recreated=False,
                )

            if r_exit != 0:
                err_msg = r_stderr or r_json_err or f"Exit code {r_exit}"
                return CodingBackendResult(
                    external_session_id=None,
                    output=r_text,
                    exit_code=r_exit,
                    error_message=err_msg,
                    cancelled=False,
                    session_recreated=False,
                )

            return CodingBackendResult(
                external_session_id=r_thread_id,
                output=r_text,
                exit_code=0,
                error_message=None,
                cancelled=False,
                session_recreated=True,
            )

        # Normal completion (initial or valid continuation)
        err_msg = None
        if exit_code != 0:
            err_msg = stderr or json_err or f"Exit code {exit_code}"

        return CodingBackendResult(
            external_session_id=current_thread_id,
            output=parsed_text,
            exit_code=exit_code,
            error_message=err_msg,
            cancelled=False,
            session_recreated=False,
        )


class OpenCodeCliBackend(_BaseSubprocessBackend):
    """OpenCode CLI backend adapter."""

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Strip ANSI escape sequences from text."""
        ansi_regex = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        return ansi_regex.sub("", text)

    @staticmethod
    def _parse_opencode_json_output(stdout: str, stderr: str) -> tuple[Optional[str], str]:
        """Parse OpenCode CLI JSON Lines output.

        Extracts session ID (e.g. ses_...) and combines text contents.
        If non-JSON output, returns (extracted_session_id, raw_output).
        """
        import json

        extracted_session_id = None
        text_parts: list[str] = []

        combined = stdout + "\n" + stderr if stderr else stdout
        for line in combined.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    data = json.loads(line_str)
                    if isinstance(data, dict):
                        # Extract session ID from top level or nested fields
                        if "sessionID" in data and data["sessionID"]:
                            extracted_session_id = str(data["sessionID"])
                        elif "session_id" in data and data["session_id"]:
                            extracted_session_id = str(data["session_id"])
                        elif "session" in data and isinstance(data["session"], dict) and "id" in data["session"]:
                            extracted_session_id = str(data["session"]["id"])
                        elif "sessionId" in data and data["sessionId"]:
                            extracted_session_id = str(data["sessionId"])

                        # Extract text message content from nested part objects or direct fields
                        if "part" in data and isinstance(data["part"], dict):
                            part = data["part"]
                            if part.get("type") == "text":
                                if "text" in part and isinstance(part["text"], str):
                                    text_parts.append(part["text"])
                                elif "content" in part and isinstance(part["content"], str):
                                    text_parts.append(part["content"])
                        elif "parts" in data and isinstance(data["parts"], list):
                            for part in data["parts"]:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    if "text" in part and isinstance(part["text"], str):
                                        text_parts.append(part["text"])
                                    elif "content" in part and isinstance(part["content"], str):
                                        text_parts.append(part["content"])
                        elif "text" in data and isinstance(data["text"], str):
                            text_parts.append(data["text"])
                        elif "content" in data and isinstance(data["content"], str):
                            text_parts.append(data["content"])
                        elif "message" in data:
                            msg = data["message"]
                            if isinstance(msg, str):
                                text_parts.append(msg)
                            elif isinstance(msg, dict) and "content" in msg:
                                text_parts.append(str(msg["content"]))
                except json.JSONDecodeError:
                    pass

        # Fallback session ID extraction if not found in structured JSON
        if not extracted_session_id:
            m = re.search(r"(ses_[a-zA-Z0-9]+)", combined)
            if m:
                extracted_session_id = m.group(1)

        output_text = "\n".join(text_parts).strip() if text_parts else stdout.strip() or stderr.strip()
        return extracted_session_id, output_text

    def execute(
        self,
        repo_path: str,
        prompt: str,
        external_session_id: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout: int = 600,
    ) -> CodingBackendResult:
        exe_path = CODING_OPENCODE_CLI_PATH or "opencode"

        def _run_cmd(sess_id_opt: Optional[str]):
            argv = [exe_path, "run", "--format", "json"]
            if sess_id_opt:
                argv.extend(["--session", sess_id_opt])
            argv.append(prompt)
            return self._run_subprocess(
                argv, cwd=repo_path, cancel_event=cancel_event, timeout=timeout
            )

        try:
            exit_code, stdout, stderr, cancelled = _run_cmd(external_session_id)
        except Exception as exc:
            logger.exception("Failed to execute OpenCode CLI")
            return CodingBackendResult(
                external_session_id=external_session_id,
                output="",
                exit_code=-1,
                error_message=str(exc),
                cancelled=False,
            )

        if cancelled:
            _, parsed_text = self._parse_opencode_json_output(stdout, stderr)
            return CodingBackendResult(
                external_session_id=external_session_id,
                output=parsed_text,
                exit_code=exit_code,
                error_message="Cancelled by user or timed out",
                cancelled=True,
            )

        clean_combined = self._strip_ansi(stdout + "\n" + stderr)

        # Check for Session not found when an external_session_id was provided
        if external_session_id and "Session not found" in clean_combined:
            logger.warning(
                "OpenCode session '%s' not found. Retrying once with a new session...",
                external_session_id,
            )
            try:
                r_exit, r_stdout, r_stderr, r_cancelled = _run_cmd(None)
            except Exception as exc:
                logger.exception("Failed during OpenCode retry execution")
                return CodingBackendResult(
                    external_session_id=None,
                    output="",
                    exit_code=-1,
                    error_message=f"Retry failed: {str(exc)}",
                    cancelled=False,
                    session_recreated=True,
                )

            if r_cancelled:
                _, r_text = self._parse_opencode_json_output(r_stdout, r_stderr)
                return CodingBackendResult(
                    external_session_id=None,
                    output=r_text,
                    exit_code=r_exit,
                    error_message="Cancelled by user or timed out during retry",
                    cancelled=True,
                    session_recreated=True,
                )

            if r_exit != 0:
                _, r_text = self._parse_opencode_json_output(r_stdout, r_stderr)
                return CodingBackendResult(
                    external_session_id=None,
                    output=r_text,
                    exit_code=r_exit,
                    error_message=r_stderr or f"Exit code {r_exit}",
                    cancelled=False,
                    session_recreated=True,
                )

            r_sess_id, r_text = self._parse_opencode_json_output(r_stdout, r_stderr)
            return CodingBackendResult(
                external_session_id=r_sess_id,
                output=r_text,
                exit_code=0,
                error_message=None,
                cancelled=False,
                session_recreated=True,
            )

        # Normal completion (initial or valid continuation)
        extracted_sess_id, parsed_text = self._parse_opencode_json_output(stdout, stderr)
        final_sess_id = extracted_sess_id or external_session_id
        err_msg = None if exit_code == 0 else (stderr or f"Exit code {exit_code}")

        return CodingBackendResult(
            external_session_id=final_sess_id,
            output=parsed_text,
            exit_code=exit_code,
            error_message=err_msg,
            cancelled=False,
            session_recreated=False,
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
