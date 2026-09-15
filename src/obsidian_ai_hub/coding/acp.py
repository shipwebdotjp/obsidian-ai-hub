"""ACP Client Backend and Launch Profiles for Codex and OpenCode."""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from obsidian_ai_hub.utils.config import (
    CODING_CODEX_CLI_PATH,
    CODING_OPENCODE_CLI_PATH,
)

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSIONS = ("1.0", "1.1", "1.2", "2024-11-05", "2025-01-01")
DEFAULT_ACP_TURN_TIMEOUT_S = 600.0


class AcpError(Exception):
    """Base exception for ACP protocol/transport errors."""

    pass


class AcpCapabilityMismatchError(AcpError):
    """Raised when server protocol version or required capabilities are missing."""

    pass


class AcpPermissionRejectedError(AcpError):
    """Raised when an unhandled permission request is received."""

    pass


@dataclass
class AcpLaunchProfile:
    """Launch configuration profile for an ACP Agent subprocess."""

    profile_id: str  # e.g., "codex_acp", "opencode_acp"
    backend_name: str  # "codex" or "opencode"
    executable: str
    argv: List[str]
    env_overrides: Dict[str, str] = field(default_factory=dict)
    supports_resume: bool = True

    @classmethod
    def get_profile(cls, backend_name: str) -> AcpLaunchProfile:
        b = (backend_name or "").strip().lower()
        if b == "codex":
            exe = os.getenv("CODING_CODEX_ACP_PATH") or CODING_CODEX_CLI_PATH or "codex-acp"
            if exe == "codex" or exe.endswith("/codex"):
                exe = "codex-acp"
            return cls(
                profile_id="codex_acp",
                backend_name="codex",
                executable=exe,
                argv=[exe],
                supports_resume=True,
            )
        elif b == "opencode":
            exe = CODING_OPENCODE_CLI_PATH or "opencode"
            return cls(
                profile_id="opencode_acp",
                backend_name="opencode",
                executable=exe,
                argv=[exe, "acp"],
                supports_resume=True,
            )
        else:
            raise ValueError(f"Unknown ACP backend: '{backend_name}' (expected 'codex' or 'opencode')")


@dataclass
class AcpExecutionResult:
    acp_session_id: Optional[str]
    output: str
    exit_code: int
    stop_reason: Optional[str] = None
    error_message: Optional[str] = None
    cancelled: bool = False
    session_recreated: bool = False
    diagnostics: Optional[Dict[str, Any]] = None


class AcpConnection:
    """Stdio JSON-RPC 2.0 connection to an ACP Agent subprocess."""

    def __init__(
        self,
        argv: List[str],
        cwd: str,
        env: Optional[Dict[str, str]] = None,
    ):
        self.argv = argv
        self.cwd = cwd
        self.env = env if env is not None else os.environ.copy()
        self.proc: Optional[subprocess.Popen] = None
        self.pgid: Optional[int] = None
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._responses: Dict[int, queue.Queue] = {}
        self._resp_lock = threading.Lock()
        self._notifications: queue.Queue = queue.Queue()
        self._client_requests: queue.Queue = queue.Queue()
        self.stderr_chunks: List[str] = []
        self._threads: List[threading.Thread] = []
        self._closed = False

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.argv,
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=True,
        )
        assert self.proc.pid is not None
        try:
            self.pgid = os.getpgid(self.proc.pid)
        except (OSError, AttributeError):
            self.pgid = self.proc.pid

        t_out = threading.Thread(target=self._read_stdout, daemon=True)
        t_err = threading.Thread(target=self._read_stderr, daemon=True)
        t_out.start()
        t_err.start()
        self._threads = [t_out, t_err]

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        try:
            for line in iter(self.proc.stdout.readline, ""):
                text = line.rstrip("\r\n")
                if not text.strip():
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue

                if "id" in msg and ("result" in msg or "error" in msg):
                    with self._resp_lock:
                        q = self._responses.get(msg["id"])
                    if q is not None:
                        q.put(msg)
                    else:
                        self._notifications.put(msg)
                elif "method" in msg and "id" in msg:
                    self._client_requests.put(msg)
                else:
                    self._notifications.put(msg)
        finally:
            try:
                self.proc.stdout.close()
            except Exception:
                pass

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        try:
            for line in iter(self.proc.stderr.readline, ""):
                self.stderr_chunks.append(line.rstrip("\r\n"))
        finally:
            try:
                self.proc.stderr.close()
            except Exception:
                pass

    def next_id(self) -> int:
        with self._id_lock:
            self._next_id += 1
            return self._next_id

    def _send(self, payload: Dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        data = json.dumps(payload, ensure_ascii=False)
        self.proc.stdin.write(data + "\n")
        self.proc.stdin.flush()

    def request(
        self, method: str, params: Dict[str, Any], timeout: float = 60.0
    ) -> Dict[str, Any]:
        rid = self.next_id()
        q: queue.Queue = queue.Queue()
        with self._resp_lock:
            self._responses[rid] = q
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            try:
                res = q.get(timeout=timeout)
                if "error" in res:
                    err = res["error"]
                    err_msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise AcpError(f"RPC error on {method}: {err_msg}")
                return res.get("result", {})
            except queue.Empty:
                raise AcpError(f"Timeout ({timeout}s) waiting for response to RPC method '{method}' (id={rid})")
        finally:
            with self._resp_lock:
                self._responses.pop(rid, None)

    def notify(self, method: str, params: Dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def respond(self, rid: int, result: Any) -> None:
        self._send({"jsonrpc": "2.0", "id": rid, "result": result})

    def respond_error(self, rid: int, code: int, message: str) -> None:
        self._send(
            {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}
        )

    def send_request_async(self, method: str, params: Dict[str, Any]) -> int:
        """Send a request without blocking; caller correlates via wait_for_response."""
        rid = self.next_id()
        q: queue.Queue = queue.Queue()
        with self._resp_lock:
            self._responses[rid] = q
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return rid

    def wait_for_response(self, rid: int, timeout: float) -> Optional[Dict[str, Any]]:
        with self._resp_lock:
            q = self._responses.get(rid)
        if q is None:
            return None
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def pop_notifications(self) -> List[Dict[str, Any]]:
        out = []
        while True:
            try:
                out.append(self._notifications.get_nowait())
            except queue.Empty:
                return out

    def pop_client_requests(self) -> List[Dict[str, Any]]:
        out = []
        while True:
            try:
                out.append(self._client_requests.get_nowait())
            except queue.Empty:
                return out

    def terminate(self, grace_s: float = 3.0) -> int:
        if not self.proc or self._closed:
            return 0
        self._closed = True
        try:
            if self.proc.poll() is None and self.pgid is not None:
                os.killpg(self.pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            exit_code = self.proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            try:
                if self.pgid is not None:
                    os.killpg(self.pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            exit_code = self.proc.wait(timeout=5.0)
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        for t in self._threads:
            t.join(timeout=1.0)
        return exit_code


class AcpClientBackend:
    """ACP Client Backend managing stdio connection lifecycle, protocol initialization, session setup, and prompt turn."""

    def __init__(self, profile: AcpLaunchProfile):
        self.profile = profile

    def _prepare_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env.update(self.profile.env_overrides)
        return env

    def initialize(self, conn: AcpConnection, timeout: float = 30.0) -> Dict[str, Any]:
        """Perform mandatory ACP protocol initialization and capability negotiation."""
        params = {
            "protocolVersion": "1.0",
            "clientInfo": {
                "name": "obsidian-ai-hub",
                "version": "1.0.0",
            },
            # Non-advertised capabilities
            "capabilities": {
                "fs": False,
                "terminal": False,
                "elicitation": False,
            },
        }
        res = conn.request("initialize", params, timeout=timeout)
        version = res.get("protocolVersion") or res.get("version")
        if version and str(version) not in SUPPORTED_PROTOCOL_VERSIONS and not str(version).startswith("1."):
            logger.warning("Agent returned unexpected ACP protocol version '%s'", version)

        agent_capabilities = res.get("capabilities") or {}
        return {
            "protocol_version": version or "1.0",
            "agent_info": res.get("agentInfo") or res.get("agent_info") or {},
            "capabilities": agent_capabilities,
        }

    def _handle_permission_request(self, req: Dict[str, Any], conn: AcpConnection) -> Tuple[bool, str]:
        """Handle session/request_permission RPC request from ACP agent.

        Pre-defined policy: check if options contain an 'allow' outcome/id/value.
        If found, respond with selected option. Otherwise, reject and raise AcpPermissionRejectedError.
        No HITL run is created for unhandled technical permissions.
        """
        rid = req.get("id")
        params = req.get("params") or {}
        options = params.get("options") or []

        selected_option = None
        for opt in options:
            if isinstance(opt, dict):
                opt_id = str(opt.get("option_id") or opt.get("id") or opt.get("value") or "").lower()
                outcome = str(opt.get("outcome") or "").lower()
                if opt_id in ("allow", "yes", "accept", "permit") or outcome == "allow":
                    selected_option = opt
                    break

        if selected_option is not None and rid is not None:
            option_id = selected_option.get("option_id") or selected_option.get("id") or selected_option.get("value")
            conn.respond(rid, {"outcome": "allow", "selected_option_id": option_id, "option_id": option_id})
            return True, f"Allowed permission option '{option_id}'"
        else:
            if rid is not None:
                conn.respond_error(rid, -32601, "Permission denied by client policy")
            raise AcpPermissionRejectedError(
                f"ACP agent requested permission with options {options}, which is not in pre-defined allowlist"
            )

    def execute_turn(
        self,
        repo_path: str,
        prompt: str,
        acp_session_id: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout: Optional[float] = DEFAULT_ACP_TURN_TIMEOUT_S,
        on_update_callback: Optional[Any] = None,
    ) -> AcpExecutionResult:
        """Execute a single ACP prompt turn with full session lifecycle handling."""
        env = self._prepare_env()
        conn = AcpConnection(
            argv=self.profile.argv,
            cwd=repo_path,
            env=env,
        )

        try:
            conn.start()
        except Exception as exc:
            return AcpExecutionResult(
                acp_session_id=acp_session_id,
                output="",
                exit_code=-1,
                error_message=f"Failed to launch ACP subprocess '{self.profile.executable}': {exc}",
            )

        session_recreated = False
        init_meta = {}
        curr_session_id = acp_session_id

        try:
            init_meta = self.initialize(conn, timeout=15.0)

            # Session resolution (new or resume)
            if curr_session_id:
                agent_caps = init_meta.get("capabilities", {})
                can_resume = bool(agent_caps.get("resume") or agent_caps.get("load") or self.profile.supports_resume)
                if can_resume:
                    try:
                        resume_method = "session/resume" if agent_caps.get("resume") else "session/load"
                        conn.request(resume_method, {"session_id": curr_session_id, "sessionId": curr_session_id}, timeout=15.0)
                    except AcpError as exc:
                        logger.warning("Failed to resume ACP session '%s': %s. Fallback to session/new...", curr_session_id, exc)
                        curr_session_id = None
                        session_recreated = True
                else:
                    curr_session_id = None
                    session_recreated = True

            if not curr_session_id:
                new_res = conn.request("session/new", {"cwd": repo_path, "repo_path": repo_path}, timeout=15.0)
                curr_session_id = (
                    new_res.get("sessionId")
                    or new_res.get("session_id")
                    or (new_res.get("session") or {}).get("id")
                )
                if not curr_session_id:
                    raise AcpError("ACP session/new response did not return a valid session ID")

            # Send session/prompt request asynchronously to process streaming notifications
            prompt_params = {
                "sessionId": curr_session_id,
                "session_id": curr_session_id,
                "prompt": prompt,
            }
            prompt_req_id = conn.send_request_async("session/prompt", prompt_params)

            output_chunks: List[str] = []
            stop_reason: Optional[str] = None
            start_time = time.monotonic()
            poll_interval = 0.1
            cancelled = False
            prompt_response: Optional[Dict[str, Any]] = None

            while True:
                # Check cancellation
                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    try:
                        conn.notify("session/cancel", {"sessionId": curr_session_id, "session_id": curr_session_id})
                    except Exception:
                        pass
                    break

                # Check timeout
                if timeout is not None and (time.monotonic() - start_time) >= timeout:
                    cancelled = True
                    try:
                        conn.notify("session/cancel", {"sessionId": curr_session_id, "session_id": curr_session_id})
                    except Exception:
                        pass
                    break

                # Check client requests (permissions)
                for client_req in conn.pop_client_requests():
                    method = client_req.get("method")
                    if method in ("session/request_permission", "request_permission"):
                        self._handle_permission_request(client_req, conn)

                # Process notifications (updates)
                for notif in conn.pop_notifications():
                    method = notif.get("method")
                    params = notif.get("params") or {}
                    if method in ("session/update", "update"):
                        text = params.get("text") or params.get("content")
                        if text and isinstance(text, str):
                            output_chunks.append(text)
                        elif "part" in params and isinstance(params["part"], dict):
                            part = params["part"]
                            if part.get("type") == "text" and isinstance(part.get("text"), str):
                                output_chunks.append(part["text"])

                        sr = params.get("stop_reason") or params.get("stopReason")
                        if sr:
                            stop_reason = str(sr)

                        if on_update_callback:
                            try:
                                on_update_callback(params)
                            except Exception:
                                pass

                # Check prompt RPC response completion
                res = conn.wait_for_response(prompt_req_id, timeout=poll_interval)
                if res is not None:
                    prompt_response = res
                    break

                # Check process exit prematurely
                if not conn.is_alive():
                    break

            # Handle finished turn response
            if prompt_response and "error" in prompt_response:
                err_dict = prompt_response["error"]
                err_msg = err_dict.get("message") if isinstance(err_dict, dict) else str(err_dict)
                raise AcpError(f"ACP session/prompt error: {err_msg}")

            if prompt_response and "result" in prompt_response:
                res_data = prompt_response["result"] or {}
                if isinstance(res_data, dict):
                    res_text = res_data.get("output") or res_data.get("text") or res_data.get("content")
                    if res_text and isinstance(res_text, str) and not output_chunks:
                        output_chunks.append(res_text)
                    sr = res_data.get("stop_reason") or res_data.get("stopReason")
                    if sr:
                        stop_reason = str(sr)

            final_output = "".join(output_chunks).strip()
            stderr_str = "\n".join(conn.stderr_chunks).strip()

            # Attempt graceful session/close notify
            try:
                conn.notify("session/close", {"sessionId": curr_session_id, "session_id": curr_session_id})
            except Exception:
                pass

            exit_code = conn.terminate(grace_s=2.0)

            diag = {
                "acp_version": init_meta.get("protocol_version"),
                "acp_profile_id": self.profile.profile_id,
                "acp_capabilities": init_meta.get("capabilities"),
                "stop_reason": stop_reason,
                "session_recreated": session_recreated,
                "stderr_snippet": stderr_str[:500] if stderr_str else None,
            }

            return AcpExecutionResult(
                acp_session_id=curr_session_id,
                output=final_output,
                exit_code=exit_code if not cancelled else -1,
                stop_reason=stop_reason,
                error_message="Cancelled by user or timed out" if cancelled else (stderr_str if exit_code != 0 and stderr_str else None),
                cancelled=cancelled,
                session_recreated=session_recreated,
                diagnostics=diag,
            )

        except Exception as exc:
            logger.exception("Error during ACP turn execution")
            conn.terminate(grace_s=1.0)
            return AcpExecutionResult(
                acp_session_id=curr_session_id or acp_session_id,
                output="",
                exit_code=-1,
                error_message=str(exc),
                cancelled=False,
                session_recreated=session_recreated,
                diagnostics={
                    "acp_profile_id": self.profile.profile_id,
                    "error": str(exc),
                },
            )
