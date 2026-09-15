"""ACP Client Backend and Launch Profile for OpenCode (ACP-only)."""

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
    CODING_OPENCODE_CLI_PATH,
    CODING_OPENCODE_MODEL,
)

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSION = 1
DEFAULT_ACP_TURN_TIMEOUT_S = 600.0

# Single source of truth for the advertised elicitation capability (form only).
ELICITATION_FORM_CAPABILITY: Dict[str, Any] = {"form": {}}


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
    """Launch configuration profile for the OpenCode ACP Agent subprocess."""

    profile_id: str  # "opencode_acp"
    backend_name: str  # "opencode" (fixed; the workspace is OpenCode-only)
    executable: str
    argv: List[str]
    env_overrides: Dict[str, str] = field(default_factory=dict)
    supports_resume: bool = True
    expected_version: Optional[str] = None

    @classmethod
    def get_profile(cls, backend_name: str) -> AcpLaunchProfile:
        b = (backend_name or "").strip().lower()
        if b != "opencode":
            raise ValueError(f"Unknown ACP backend: '{backend_name}' (expected 'opencode')")
        exe = CODING_OPENCODE_CLI_PATH or "opencode"
        # --hostname/--port are mandatory: bare `opencode acp` dies with
        # ServeError (1.18.31, see compatibility-matrix).
        return cls(
            profile_id="opencode_acp",
            backend_name="opencode",
            executable=exe,
            argv=[exe, "acp", "--hostname", "127.0.0.1", "--port", "0"],
            supports_resume=True,
            expected_version="1.18.31",
        )


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
            "protocolVersion": SUPPORTED_PROTOCOL_VERSION,
            "clientCapabilities": {
                # Omitted capabilities mean unsupported: fs/terminal/url stay
                # non-advertised; elicitation form only (D3).
                "elicitation": dict(ELICITATION_FORM_CAPABILITY),
            },
            "clientInfo": {
                "name": "obsidian-ai-hub",
                "version": "1.0.0",
            },
        }
        res = conn.request("initialize", params, timeout=timeout)
        version = res.get("protocolVersion", res.get("version", SUPPORTED_PROTOCOL_VERSION))
        try:
            version_int = int(version)
        except (TypeError, ValueError):
            version_int = -1
        if version_int != SUPPORTED_PROTOCOL_VERSION:
            raise AcpCapabilityMismatchError(
                f"ACP protocol version mismatch: agent returned '{version}', "
                f"client supports v{SUPPORTED_PROTOCOL_VERSION}."
            )

        agent_capabilities = res.get("agentCapabilities") or res.get("capabilities") or {}
        if not isinstance(agent_capabilities, dict):
            agent_capabilities = {}
        return {
            "protocol_version": version_int,
            "agent_info": res.get("agentInfo") or res.get("agent_info") or {},
            "capabilities": agent_capabilities,
        }

    def _apply_session_model(self, conn: AcpConnection, session_id: str) -> None:
        """Pin the configured OpenCode model on the ACP session.

        Raises AcpError on rejection: a misconfigured model name must fail
        the turn instead of silently running on the agent default.
        """
        model = (CODING_OPENCODE_MODEL or "").strip()
        if not model:
            raise AcpError(
                "OpenCode model is not configured (coding.acp.opencode_model / "
                "CODING_OPENCODE_MODEL); refusing to run on an unknown model."
            )
        try:
            conn.request(
                "session/set_model",
                {"sessionId": session_id, "modelId": model},
                timeout=15.0,
            )
        except AcpError as exc:
            raise AcpError(
                f"Failed to set OpenCode model '{model}' on ACP session "
                f"'{session_id}': {exc}. Check coding.acp.opencode_model / "
                "CODING_OPENCODE_MODEL."
            ) from exc
        logger.info("ACP session '%s' model set to '%s'.", session_id, model)

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

    def _handle_elicitation_request(
        self,
        req: Dict[str, Any],
        conn: AcpConnection,
        *,
        on_elicitation_create: Optional[Any],
        cancel_event: Optional[threading.Event],
        deadline_monotonic: float,
        connection_token: str,
    ) -> Dict[str, Any]:
        """Handle an elicitation/create RPC request from the ACP agent.

        Form mode is routed to on_elicitation_create (same-connection reply,
        backed by the existing coding.ask_user HITL in the service layer).
        Unadvertised modes and invalid schemas get a -32602 error reply and the
        turn continues. Unexpected handler failures get a -32603 reply and fail
        the turn loudly instead of masking the failure.
        """
        from obsidian_ai_hub.coding import acp_elicitation as acp_el

        rid = req.get("id")
        params = req.get("params") or {}
        if rid is None:
            # elicitation/create is a request, not a notification: without an
            # id no reply is possible, so fail the turn loudly instead of
            # creating orphan HITL state.
            raise AcpError("elicitation/create without a request id is not supported.")
        try:
            parsed = acp_el.parse_elicitation_create(params)
        except acp_el.AcpElicitationError as exc:
            if rid is not None:
                try:
                    conn.respond_error(rid, exc.code, str(exc))
                except Exception:
                    logger.warning("Failed to send elicitation error reply", exc_info=True)
            logger.warning("Rejecting elicitation/create: %s", exc)
            return {"request_id": rid, "action": "error", "error": str(exc)}

        if on_elicitation_create is None:
            if rid is not None:
                try:
                    conn.respond(rid, {"action": "cancel"})
                except Exception:
                    logger.warning("Failed to send elicitation cancel reply", exc_info=True)
            logger.warning("No elicitation handler; replied cancel to elicitation/create.")
            return {"request_id": rid, "action": "cancel", "unhandled": True}

        wait_ctx = {
            "deadline_monotonic": deadline_monotonic,
            "cancel_event": cancel_event,
            "connection_token": connection_token,
            "request_id": rid,
        }
        try:
            result = on_elicitation_create(parsed, wait_ctx)
        except acp_el.AcpElicitationDeclined:
            result = {"action": "decline"}
        except acp_el.AcpElicitationCancelled as exc:
            logger.info("Elicitation cancelled: %s", exc)
            result = {"action": "cancel"}
        except Exception as exc:
            if rid is not None:
                try:
                    conn.respond_error(rid, -32603, f"Elicitation handler failed: {exc}")
                except Exception:
                    logger.warning("Failed to send elicitation error reply", exc_info=True)
            raise AcpError(f"Elicitation handler failed: {exc}") from exc
        if (
            not isinstance(result, dict)
            or result.get("action") not in ("accept", "decline", "cancel")
            or (result.get("action") == "accept" and not isinstance(result.get("content"), dict))
        ):
            if rid is not None:
                try:
                    conn.respond_error(rid, -32603, "Elicitation handler returned invalid result")
                except Exception:
                    logger.warning("Failed to send elicitation error reply", exc_info=True)
            raise AcpError(
                "Elicitation handler returned an invalid result; failing the turn."
            )
        if rid is not None:
            conn.respond(rid, result)
        message_snippet = (parsed.message or "")[:200]
        return {
            "request_id": rid,
            "action": result.get("action"),
            "message": message_snippet,
            "properties": [p.name for p in parsed.properties],
        }

    def execute_turn(
        self,
        repo_path: str,
        prompt: str,
        acp_session_id: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout: Optional[float] = DEFAULT_ACP_TURN_TIMEOUT_S,
        on_update_callback: Optional[Any] = None,
        on_elicitation_create: Optional[Any] = None,
    ) -> AcpExecutionResult:
        """Execute a single ACP prompt turn with full session lifecycle handling.

        on_elicitation_create, when given, is called for each form-mode
        elicitation/create request as ``callback(parsed, wait_ctx)`` where
        parsed is the validated request dict and wait_ctx carries
        ``deadline_monotonic``, ``cancel_event``, ``connection_token`` and
        ``request_id``. It returns the JSON-RPC result payload
        (``{"action": "accept"|"decline"|"cancel", "content"?: {...}}``) or
        raises AcpElicitationDeclined / AcpElicitationCancelled, which are
        translated to decline/cancel replies. Without a callback, form
        elicitations are answered with cancel (no user to ask).
        """
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

            # Session resolution (new / resume / load) per advertised capabilities.
            agent_caps = init_meta.get("capabilities", {})
            session_caps = agent_caps.get("sessionCapabilities") or {}
            if curr_session_id:
                resume_ok = bool(
                    (session_caps.get("resume") is not None)
                    and self.profile.supports_resume
                )
                load_ok = bool(agent_caps.get("loadSession"))
                if resume_ok:
                    resume_method: Optional[str] = "session/resume"
                elif load_ok:
                    resume_method = "session/load"
                else:
                    resume_method = None
                if resume_method is not None:
                    try:
                        conn.request(
                            resume_method,
                            {
                                "sessionId": curr_session_id,
                                "cwd": repo_path,
                                "mcpServers": [],
                            },
                            timeout=15.0,
                        )
                    except AcpError as exc:
                        logger.warning("Failed to resume ACP session '%s': %s. Fallback to session/new...", curr_session_id, exc)
                        curr_session_id = None
                        session_recreated = True
                else:
                    curr_session_id = None
                    session_recreated = True

            if not curr_session_id:
                new_res = conn.request(
                    "session/new", {"cwd": repo_path, "mcpServers": []}, timeout=15.0
                )
                curr_session_id = new_res.get("sessionId")
                if not curr_session_id or not isinstance(curr_session_id, str):
                    raise AcpError("ACP session/new response did not return a valid session ID")

            # Pin the OpenCode-side model before prompting (per-prompt model
            # params are ignored by OpenCode; fail the turn on rejection so a
            # misconfigured model name surfaces instead of silently running
            # on the agent default).
            self._apply_session_model(conn, curr_session_id)

            # Send session/prompt request asynchronously to process streaming notifications
            prompt_params = {
                "sessionId": curr_session_id,
                "prompt": [{"type": "text", "text": prompt}],
            }
            prompt_req_id = conn.send_request_async("session/prompt", prompt_params)

            import uuid as _uuid

            output_chunks: List[str] = []
            stop_reason: Optional[str] = None
            start_time = time.monotonic()
            deadline_monotonic = (
                start_time + timeout if timeout is not None else float("inf")
            )
            connection_token = f"acpconn_{_uuid.uuid4().hex[:12]}"
            poll_interval = 0.1
            cancelled = False
            prompt_response: Optional[Dict[str, Any]] = None
            elicitations: List[Dict[str, Any]] = []
            update_kinds: Dict[str, int] = {}

            while True:
                # Check cancellation
                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    try:
                        conn.notify("session/cancel", {"sessionId": curr_session_id})
                    except Exception:
                        pass
                    break

                # Check timeout
                if timeout is not None and (time.monotonic() - start_time) >= timeout:
                    cancelled = True
                    try:
                        conn.notify("session/cancel", {"sessionId": curr_session_id})
                    except Exception:
                        pass
                    break

                # Check client requests (permissions + elicitations)
                for client_req in conn.pop_client_requests():
                    method = client_req.get("method")
                    if method in ("session/request_permission", "request_permission"):
                        self._handle_permission_request(client_req, conn)
                    elif method == "elicitation/create":
                        record = self._handle_elicitation_request(
                            client_req,
                            conn,
                            on_elicitation_create=on_elicitation_create,
                            cancel_event=cancel_event,
                            deadline_monotonic=deadline_monotonic,
                            connection_token=connection_token,
                        )
                        elicitations.append(record)

                # Process notifications (updates)
                for notif in conn.pop_notifications():
                    method = notif.get("method")
                    params = notif.get("params") or {}
                    if method in ("session/update", "update"):
                        # Flat shapes plus the spec-shaped nested update form
                        # (params.update.sessionUpdate with content.text), as
                        # observed in Phase 0 artifacts for both profiles.
                        texts: List[str] = []
                        top_text = params.get("text")
                        if isinstance(top_text, str) and top_text:
                            texts.append(top_text)
                        top_content = params.get("content")
                        if isinstance(top_content, str) and top_content:
                            texts.append(top_content)
                        elif isinstance(top_content, dict) and isinstance(
                            top_content.get("text"), str
                        ):
                            texts.append(top_content["text"])
                        nested = params.get("update")
                        if isinstance(nested, dict):
                            nested_content = nested.get("content")
                            if isinstance(nested_content, dict) and isinstance(
                                nested_content.get("text"), str
                            ):
                                texts.append(nested_content["text"])
                            elif isinstance(nested_content, list):
                                for part in nested_content:
                                    if (
                                        isinstance(part, dict)
                                        and part.get("type") == "text"
                                        and isinstance(part.get("text"), str)
                                    ):
                                        texts.append(part["text"])
                        flat_part = params.get("part")
                        if (
                            isinstance(flat_part, dict)
                            and flat_part.get("type") == "text"
                            and isinstance(flat_part.get("text"), str)
                        ):
                            texts.append(flat_part["text"])
                        output_chunks.extend(texts)

                        nested_update = params.get("update")
                        kind = (
                            nested_update.get("sessionUpdate")
                            if isinstance(nested_update, dict)
                            else None
                        )
                        kind_key = str(kind) if kind else "flat"
                        update_kinds[kind_key] = update_kinds.get(kind_key, 0) + 1

                        sr = params.get("stop_reason") or params.get("stopReason")
                        if sr:
                            stop_reason = str(sr)

                        if on_update_callback:
                            try:
                                on_update_callback(params)
                            except Exception:
                                pass
                    else:
                        # Unknown/custom notifications are never executed, only
                        # counted for the typed-update audit below.
                        other_key = f"ignored:{method}"
                        update_kinds[other_key] = update_kinds.get(other_key, 0) + 1

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

            # Graceful session/close only when advertised (fire-and-forget).
            if (init_meta.get("capabilities", {}).get("sessionCapabilities") or {}).get(
                "close"
            ) is not None:
                try:
                    conn.notify("session/close", {"sessionId": curr_session_id})
                except Exception:
                    pass

            exit_code = conn.terminate(grace_s=2.0)

            agent_info = init_meta.get("agent_info") or {}
            if (
                self.profile.expected_version
                and isinstance(agent_info, dict)
                and agent_info.get("version") not in (None, self.profile.expected_version)
            ):
                logger.warning(
                    "ACP agent version '%s' differs from pinned '%s' for profile '%s'",
                    agent_info.get("version"),
                    self.profile.expected_version,
                    self.profile.profile_id,
                )
            diag = {
                "acp_version": init_meta.get("protocol_version"),
                "acp_profile_id": self.profile.profile_id,
                "acp_model": CODING_OPENCODE_MODEL,
                "acp_agent": agent_info,
                "acp_capabilities": init_meta.get("capabilities"),
                "stop_reason": stop_reason,
                "session_recreated": session_recreated,
                "stderr_snippet": stderr_str[:500] if stderr_str else None,
                "elicitations": elicitations,
                "update_kinds": update_kinds,
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
