"""CLI Backend adapters for Codex CLI and OpenCode CLI."""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from obsidian_ai_hub.utils.config import (
    CODING_CODEX_CLI_PATH,
    CODING_OPENCODE_CLI_PATH,
    CODING_OPENCODE_AUTO_APPROVE,
    CODING_OPENCODE_MODEL,
    CODING_OPENCODE_VARIANT,
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
    diagnostics: Optional[dict] = None


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
        env: Optional[dict] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout: int = 600,
    ) -> tuple[int, str, str, bool]:
        """Run process with group signal termination on cancel/timeout.

        Returns (exit_code, stdout, stderr, cancelled).
        """
        proc_env = env if env is not None else os.environ.copy()
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=proc_env,
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
                            if "thread_id" in data and isinstance(
                                data["thread_id"], str
                            ):
                                extracted_thread_id = data["thread_id"]
                            elif "thread" in data and isinstance(data["thread"], dict):
                                thread_obj = data["thread"]
                                if "id" in thread_obj and isinstance(
                                    thread_obj["id"], str
                                ):
                                    extracted_thread_id = thread_obj["id"]

                        # Fallback for thread_id if present in top level
                        if (
                            not extracted_thread_id
                            and "thread_id" in data
                            and isinstance(data["thread_id"], str)
                        ):
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
                                elif "agent_message" in item and isinstance(
                                    item["agent_message"], dict
                                ):
                                    msg_obj = item["agent_message"]
                                    txt = msg_obj.get("text")
                                    if isinstance(txt, str) and txt:
                                        agent_messages.append(txt)

                        # 3. JSON Error event extraction
                        if event_type == "error":
                            msg = data.get("message") or data.get("error")
                            if isinstance(msg, str) and msg:
                                json_errors.append(msg)
                        elif (
                            "error" in data
                            and isinstance(data["error"], str)
                            and data["error"]
                        ):
                            json_errors.append(data["error"])

                except json.JSONDecodeError:
                    pass

        # Return the last non-empty agent_message as final output, or fallback to stdout/stderr
        output_text = (
            agent_messages[-1] if agent_messages else (stdout.strip() or stderr.strip())
        )
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

        extracted_thread_id, parsed_text, json_err = self._parse_codex_json_output(
            stdout, stderr
        )
        current_thread_id = extracted_thread_id or external_session_id

        if cancelled:
            return CodingBackendResult(
                external_session_id=current_thread_id,
                output=parsed_text,
                exit_code=exit_code,
                error_message="Cancelled by user or timed out",
                cancelled=True,
            )

        # Same false-positive risk as OpenCode: tool outputs inside JSON lines may
        # contain literal "session not found"/"thread not found". Use only
        # exit_code, structured json_err and stderr/plain stdout, not full combined.
        def _is_codex_not_found(
            ec: int, jerr: Optional[str], sout: str, serr: str
        ) -> bool:
            if ec == 0:
                return False
            jerr_l = (jerr or "").lower()
            if "session not found" in jerr_l or "thread not found" in jerr_l:
                return True
            serr_l = self._strip_ansi(serr or "").lower()
            if "session not found" in serr_l or "thread not found" in serr_l:
                return True
            for _line in (sout or "").splitlines():
                _s = _line.strip()
                if not _s:
                    continue
                if _s.startswith("{") and _s.endswith("}"):
                    continue
                _sl = self._strip_ansi(_s).lower()
                if "session not found" in _sl or "thread not found" in _sl:
                    return True
            return False

        if external_session_id and _is_codex_not_found(
            exit_code, json_err, stdout, stderr
        ):
            logger.warning(
                "Codex thread '%s' not found (exit=%s). Retrying once with a new thread...",
                external_session_id,
                exit_code,
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

            r_thread_id, r_text, r_json_err = self._parse_codex_json_output(
                r_stdout, r_stderr
            )

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
    def _extract_title_from_export_json(json_str: str) -> Optional[str]:
        """Safely extract info.title from `opencode export` JSON output.

        Returns stripped title if present and non-empty, otherwise None.
        Never raises.
        """
        import json

        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        info = data.get("info")
        if not isinstance(info, dict):
            return None
        title = info.get("title")
        if not isinstance(title, str):
            return None
        stripped = title.strip()
        return stripped if stripped else None

    @staticmethod
    def fetch_opencode_session_title(session_id: str) -> Optional[str]:
        """Fetch OpenCode external session title via `opencode export`.

        Uses `opencode export <session_id>` and extracts info.title.
        Uses a temporary file for stdout to avoid pipe truncation on large
        export JSON (opencode 1.18.26 truncates pipe output at ~64KB).
        Returns None on any failure, empty title, JSON error, or missing field.
        Never raises. Never logs export body or full title.
        """
        if not session_id or not isinstance(session_id, str):
            return None
        exe_path = CODING_OPENCODE_CLI_PATH or "opencode"
        import tempfile

        tmp_path: Optional[Path] = None
        try:
            # Create temp file for stdout (not deleted on close, manual cleanup)
            with tempfile.NamedTemporaryFile(
                mode="w+", delete=False, suffix=".json", encoding="utf-8"
            ) as tmp:
                tmp_path = Path(tmp.name)

            # stdout -> file, stderr -> PIPE (small header like "Exporting session: ...")
            with open(tmp_path, "w", encoding="utf-8") as out_file:
                proc = subprocess.run(
                    [exe_path, "export", session_id],
                    stdout=out_file,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                )

            stderr_snippet = ""
            if proc.stderr:
                stderr_snippet = proc.stderr.strip()[:500]

            if proc.returncode != 0:
                logger.warning(
                    "opencode export failed for session %s: category=non_zero_exit returncode=%s stderr=%.500s",
                    session_id,
                    proc.returncode,
                    stderr_snippet,
                )
                return None

            # Read exported JSON from temp file
            try:
                stdout = tmp_path.read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.warning(
                    "opencode export failed for session %s: category=file_read_error error=%s returncode=%s stderr=%.500s",
                    session_id,
                    exc,
                    proc.returncode,
                    stderr_snippet,
                )
                return None

            if not stdout:
                logger.warning(
                    "opencode export failed for session %s: category=empty_output returncode=%s stderr=%.500s output_size=0",
                    session_id,
                    proc.returncode,
                    stderr_snippet,
                )
                return None

            title = OpenCodeCliBackend._extract_title_from_export_json(stdout)
            if title is None:
                logger.warning(
                    "opencode export failed for session %s: category=json_parse_or_missing_title returncode=%s stderr=%.500s output_size=%s",
                    session_id,
                    proc.returncode,
                    stderr_snippet,
                    len(stdout),
                )
                return None
            return title
        except subprocess.TimeoutExpired:
            logger.warning(
                "opencode export failed for session %s: category=timeout timeout=10s",
                session_id,
            )
            return None
        except Exception as exc:
            logger.warning(
                "opencode export failed for session %s: category=exception error=%s",
                session_id,
                exc,
            )
            return None
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    @classmethod
    def _prepare_opencode_env(cls, repo_path: str) -> dict[str, str]:
        """Construct isolated subprocess environment for OpenCode CLI execution."""
        env = os.environ.copy()
        # Set canonical Git root path for PWD
        env["PWD"] = repo_path

        # Strip parent server authentication tokens
        env.pop("OPENCODE_SERVER_PASSWORD", None)
        env.pop("OPENCODE_SERVER_USERNAME", None)

        # Parse and merge OPENCODE_PERMISSION to enforce external_directory: deny
        import json

        perm_dict = {}
        raw_perm = env.get("OPENCODE_PERMISSION")
        if raw_perm:
            try:
                parsed = json.loads(raw_perm)
                if isinstance(parsed, dict):
                    perm_dict = parsed
            except json.JSONDecodeError:
                pass

        perm_dict["external_directory"] = "deny"
        env["OPENCODE_PERMISSION"] = json.dumps(perm_dict, ensure_ascii=False)
        return env

    @classmethod
    def _parse_opencode_json_details(
        cls, stdout: str, stderr: str
    ) -> tuple[Optional[str], str, int, int, Optional[str], bool]:
        """Parse OpenCode CLI JSON Lines output for text, session ID, tool stats, and errors.

        Returns (extracted_session_id, output_text, tool_call_count, tool_failure_count, structured_error, auto_rejected_permission).
        """
        import json

        extracted_session_id = None
        text_parts: list[str] = []
        tool_call_count = 0
        tool_failure_count = 0
        structured_errors: list[str] = []
        auto_rejected_permission = False

        combined = stdout + "\n" + stderr if stderr else stdout

        for line in combined.splitlines():
            line_str = line.strip()
            if not line_str:
                continue

            # Check for permission rejection strings in raw lines
            if "external_directory" in line_str and (
                "deny" in line_str or "denied" in line_str or "rejected" in line_str
            ):
                auto_rejected_permission = True
            elif (
                "permission denied" in line_str.lower()
                or "auto-rejected" in line_str.lower()
            ):
                auto_rejected_permission = True

            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    data = json.loads(line_str)
                    if isinstance(data, dict):
                        event_type = str(data.get("type", ""))

                        # 1. Session ID extraction
                        if "sessionID" in data and data["sessionID"]:
                            extracted_session_id = str(data["sessionID"])
                        elif "session_id" in data and data["session_id"]:
                            extracted_session_id = str(data["session_id"])
                        elif (
                            "session" in data
                            and isinstance(data["session"], dict)
                            and "id" in data["session"]
                        ):
                            extracted_session_id = str(data["session"]["id"])
                        elif "sessionId" in data and data["sessionId"]:
                            extracted_session_id = str(data["sessionId"])

                        # 2. Text message content
                        if "part" in data and isinstance(data["part"], dict):
                            part = data["part"]
                            ptype = part.get("type")
                            if ptype == "text":
                                if "text" in part and isinstance(part["text"], str):
                                    text_parts.append(part["text"])
                                elif "content" in part and isinstance(
                                    part["content"], str
                                ):
                                    text_parts.append(part["content"])
                            elif ptype in ("tool_use", "tool_call", "tool_execution"):
                                tool_call_count += 1
                                if part.get("error") or part.get("status") in (
                                    "failed",
                                    "error",
                                ):
                                    tool_failure_count += 1
                        elif "parts" in data and isinstance(data["parts"], list):
                            for part in data["parts"]:
                                if isinstance(part, dict):
                                    ptype = part.get("type")
                                    if ptype == "text":
                                        if "text" in part and isinstance(
                                            part["text"], str
                                        ):
                                            text_parts.append(part["text"])
                                        elif "content" in part and isinstance(
                                            part["content"], str
                                        ):
                                            text_parts.append(part["content"])
                                    elif ptype in (
                                        "tool_use",
                                        "tool_call",
                                        "tool_execution",
                                    ):
                                        tool_call_count += 1
                                        if part.get("error") or part.get("status") in (
                                            "failed",
                                            "error",
                                        ):
                                            tool_failure_count += 1
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

                        # 3. Direct Tool Events
                        if event_type in ("tool_use", "tool_call", "tool_exec"):
                            tool_call_count += 1
                            if (
                                data.get("error")
                                or data.get("status") in ("failed", "error")
                                or data.get("is_error")
                            ):
                                tool_failure_count += 1

                        # 4. Error Event Extraction
                        if event_type == "error":
                            err_obj = data.get("error")
                            if isinstance(err_obj, dict):
                                err_msg = err_obj.get("message") or str(err_obj)
                            else:
                                err_msg = str(
                                    err_obj
                                    or data.get("message")
                                    or "Unknown error event"
                                )
                            structured_errors.append(err_msg)
                            if (
                                "permission" in err_msg.lower()
                                or "denied" in err_msg.lower()
                                or "rejected" in err_msg.lower()
                            ):
                                auto_rejected_permission = True

                        elif "error" in data and data["error"]:
                            err_val = data["error"]
                            if isinstance(err_val, str):
                                structured_errors.append(err_val)
                            elif isinstance(err_val, dict):
                                structured_errors.append(
                                    err_val.get("message") or str(err_val)
                                )

                except json.JSONDecodeError:
                    pass

        # Fallback session ID extraction if not found in structured JSON
        if not extracted_session_id:
            m = re.search(r"(ses_[a-zA-Z0-9]+)", combined)
            if m:
                extracted_session_id = m.group(1)

        output_text = (
            "\n".join(text_parts).strip()
            if text_parts
            else stdout.strip() or stderr.strip()
        )
        structured_error = (
            "\n".join(structured_errors).strip() if structured_errors else None
        )

        return (
            extracted_session_id,
            output_text,
            tool_call_count,
            tool_failure_count,
            structured_error,
            auto_rejected_permission,
        )

    def execute(
        self,
        repo_path: str,
        prompt: str,
        external_session_id: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout: int = 600,
    ) -> CodingBackendResult:
        exe_path = CODING_OPENCODE_CLI_PATH or "opencode"
        canonical_repo = validate_git_repo(repo_path)
        env = self._prepare_opencode_env(canonical_repo)

        def _run_cmd(sess_id_opt: Optional[str]):
            argv = [exe_path, "run", "--format", "json", "--dir", canonical_repo]
            if CODING_OPENCODE_AUTO_APPROVE:
                argv.append("--auto")
            if CODING_OPENCODE_MODEL:
                argv.extend(["--model", CODING_OPENCODE_MODEL])
            if CODING_OPENCODE_VARIANT:
                argv.extend(["--variant", CODING_OPENCODE_VARIANT])
            if sess_id_opt:
                argv.extend(["--session", sess_id_opt])
            argv.append(prompt)
            return self._run_subprocess(
                argv,
                cwd=canonical_repo,
                env=env,
                cancel_event=cancel_event,
                timeout=timeout,
            )

        def _build_diagnostics(
            req_sess: Optional[str],
            ret_sess: Optional[str],
            tool_calls: int,
            tool_fails: int,
            struct_err: Optional[str],
            auto_rej: bool,
            exit_code: int,
            *,
            session_recreated: bool = False,
            first_attempt_exit_code: Optional[int] = None,
            first_attempt_stderr_snippet: Optional[str] = None,
            missing_session_id: bool = False,
            fallback_trigger: Optional[str] = None,
        ) -> dict:
            diag: dict = {
                "cwd": canonical_repo,
                "requested_session_id": req_sess,
                "returned_session_id": ret_sess,
                "tool_call_count": tool_calls,
                "tool_failure_count": tool_fails,
                "structured_error": struct_err,
                "auto_rejected_permission": auto_rej,
                "exit_code": exit_code,
                "model": CODING_OPENCODE_MODEL or "既定（Global default）",
                "variant": CODING_OPENCODE_VARIANT or "なし",
                "session_recreated": session_recreated,
            }
            if first_attempt_exit_code is not None:
                diag["first_attempt_exit_code"] = first_attempt_exit_code
            if first_attempt_stderr_snippet is not None:
                diag["first_attempt_stderr_snippet"] = first_attempt_stderr_snippet[
                    :500
                ]
            if missing_session_id:
                diag["missing_session_id"] = True
            if fallback_trigger is not None:
                diag["fallback_trigger"] = fallback_trigger
            return diag

        try:
            exit_code, stdout, stderr, cancelled = _run_cmd(external_session_id)
        except Exception as exc:
            logger.exception("Failed to execute OpenCode CLI")
            diag = _build_diagnostics(
                external_session_id,
                None,
                0,
                0,
                str(exc),
                False,
                -1,
                session_recreated=False,
            )
            return CodingBackendResult(
                external_session_id=external_session_id,
                output="",
                exit_code=-1,
                error_message=str(exc),
                cancelled=False,
                diagnostics=diag,
            )

        (
            extracted_sess_id,
            parsed_text,
            tool_calls,
            tool_fails,
            struct_err,
            auto_rej,
        ) = self._parse_opencode_json_details(stdout, stderr)

        if cancelled:
            diag = _build_diagnostics(
                external_session_id,
                extracted_sess_id or external_session_id,
                tool_calls,
                tool_fails,
                struct_err,
                auto_rej,
                exit_code,
                session_recreated=False,
            )
            return CodingBackendResult(
                external_session_id=external_session_id,
                output=parsed_text,
                exit_code=exit_code,
                error_message="Cancelled by user or timed out",
                cancelled=True,
                diagnostics=diag,
            )

        # Session-not-found fallback must not trigger on tool-output content.
        # Tool/file reads embed arbitrary strings (including "session not found" from
        # backend.py itself) inside JSON stdout. Use only exit_code, structured_error,
        # stderr, and plain stdout lines (excluding JSON tool-output) for detection.
        def _is_session_not_found_error(
            ec: int, se: Optional[str], sout: str, serr: str
        ) -> tuple[bool, Optional[str]]:
            if ec == 0:
                return False, None
            se_lower = (se or "").lower()
            if "session not found" in se_lower:
                return True, "structured_error"
            # sanitize stderr without stdout/tool outputs
            serr_clean = self._strip_ansi(serr or "").lower()
            if "session not found" in serr_clean:
                return True, "stderr"
            # plain stdout lines that are not JSON (tool outputs are always JSON)
            for _line in (sout or "").splitlines():
                _stripped = _line.strip()
                if not _stripped:
                    continue
                if _stripped.startswith("{") and _stripped.endswith("}"):
                    continue
                if "session not found" in self._strip_ansi(_stripped).lower():
                    return True, "stdout"
            return False, None

        is_not_found, trigger = _is_session_not_found_error(
            exit_code, struct_err, stdout, stderr
        )

        if external_session_id and is_not_found:
            logger.warning(
                "OpenCode session '%s' not found (trigger=%s exit=%s). Retrying once with a new session...",
                external_session_id,
                trigger,
                exit_code,
            )
            # Preserve first-attempt diagnostics without prompt content (P0-2)
            # Prefer structured_error / stderr snippet over stdout/tool-output.
            if struct_err:
                first_stderr_snippet = struct_err.strip()[:500]
            elif stderr and stderr.strip():
                first_stderr_snippet = stderr.strip()[:500]
            else:
                first_stderr_snippet = self._strip_ansi(stdout + "\n" + stderr).strip()[
                    :500
                ]
            try:
                r_exit, r_stdout, r_stderr, r_cancelled = _run_cmd(None)
            except Exception as exc:
                logger.exception("Failed during OpenCode retry execution")
                diag = _build_diagnostics(
                    external_session_id,
                    None,
                    0,
                    0,
                    f"Retry failed: {str(exc)}",
                    False,
                    -1,
                    session_recreated=True,
                    first_attempt_exit_code=exit_code,
                    first_attempt_stderr_snippet=first_stderr_snippet,
                    fallback_trigger=trigger,
                )
                return CodingBackendResult(
                    external_session_id=None,
                    output="",
                    exit_code=-1,
                    error_message=f"Retry failed: {str(exc)}",
                    cancelled=False,
                    session_recreated=True,
                    diagnostics=diag,
                )

            (

                r_sess_id,
                r_text,
                r_tool_calls,
                r_tool_fails,
                r_struct_err,
                r_auto_rej,
            ) = self._parse_opencode_json_details(r_stdout, r_stderr)

            if r_cancelled:
                diag = _build_diagnostics(
                    external_session_id,
                    r_sess_id,
                    r_tool_calls,
                    r_tool_fails,
                    r_struct_err,
                    r_auto_rej,
                    r_exit,
                    session_recreated=True,
                    first_attempt_exit_code=exit_code,
                    first_attempt_stderr_snippet=first_stderr_snippet,
                    fallback_trigger=trigger,
                )
                return CodingBackendResult(
                    external_session_id=None,
                    output=r_text,
                    exit_code=r_exit,
                    error_message="Cancelled by user or timed out during retry",
                    cancelled=True,
                    session_recreated=True,
                    diagnostics=diag,
                )

            err_msg = (
                r_stderr
                or r_struct_err
                or (f"Exit code {r_exit}" if r_exit != 0 else None)
            )
            diag = _build_diagnostics(
                external_session_id,
                r_sess_id,
                r_tool_calls,
                r_tool_fails,
                r_struct_err,
                r_auto_rej,
                r_exit,
                session_recreated=True,
                first_attempt_exit_code=exit_code,
                first_attempt_stderr_snippet=first_stderr_snippet,
                fallback_trigger=trigger,
            )

            return CodingBackendResult(
                external_session_id=r_sess_id,
                output=r_text,
                exit_code=r_exit,
                error_message=err_msg,
                cancelled=False,
                session_recreated=True,
                diagnostics=diag,
            )

        # Normal completion (initial or valid continuation)
        final_sess_id = extracted_sess_id or external_session_id
        # P1-1: detect missing session id on initial success without extraction
        missing_flag = False
        if external_session_id is None and extracted_sess_id is None and exit_code == 0:
            # Success exit but no ses_... found; mark observability flag and warning
            missing_flag = True
            logger.warning(
                "OpenCode execution succeeded without session id (cwd=%s exit=%s). Diagnostics will carry missing_session_id.",
                canonical_repo,
                exit_code,
            )
        err_msg = (
            struct_err
            or stderr
            or (f"Exit code {exit_code}" if exit_code != 0 else None)
        )
        diag = _build_diagnostics(
            external_session_id,
            final_sess_id,
            tool_calls,
            tool_fails,
            struct_err,
            auto_rej,
            exit_code,
            session_recreated=False,
            missing_session_id=missing_flag,
        )

        return CodingBackendResult(
            external_session_id=final_sess_id,
            output=parsed_text,
            exit_code=exit_code,
            error_message=err_msg,
            cancelled=False,
            session_recreated=False,
            diagnostics=diag,
        )


def get_backend(backend_type: str) -> CodingBackend:
    """Get coding backend adapter instance by type name."""
    b_type = (backend_type or "").lower().strip()
    if b_type == "codex":
        return CodexCliBackend()
    elif b_type == "opencode":
        return OpenCodeCliBackend()
    else:
        raise ValueError(
            f"Unknown coding backend type: '{backend_type}' (expected 'codex' or 'opencode')"
        )
