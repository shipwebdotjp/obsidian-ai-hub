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

# ACP session config option category for reasoning depth. OpenCode advertises
# model variants through a select option with id "effort"; the advertised
# option id and values are used verbatim, and only EFFORT_PRIORITY members are
# auto-selected. Other advertised values (e.g. "default") mean the agent
# default is kept.
EFFORT_CATEGORY = "thought_level"
EFFORT_OPTION_ID = "effort"
EFFORT_PRIORITY: Tuple[str, ...] = ("max", "xhigh", "high", "medium", "low")


def _extract_content_text(content: Any) -> List[str]:
    """Extract text parts from an ACP update ``content`` value.

    Handles both the single-part object form (``{"type": "text", "text": ...}``)
    and the multi-part list form observed for prompted content.
    """
    texts: List[str] = []
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            texts.append(content["text"])
    elif isinstance(content, list):
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            ):
                texts.append(part["text"])
    return texts


def _extract_usage_numbers(value: Any) -> Optional[Dict[str, Any]]:
    """Extract token usage numbers from an ACP payload.

    Verified against recorded artifacts
    (docs/acp/artifacts/opencode-1.18.31-2026-09-15/new-prompt-run.json,
    codex-1.11.0-2026-09-15/new-prompt-run.json):

    - ``session/update`` with ``sessionUpdate: "usage_update"`` carries
      ``{used, size, cost?: {amount, currency}}`` (no input/output split).
    - ``session/prompt`` result carries
      ``usage: {inputTokens, outputTokens, totalTokens, cachedReadTokens}``.

    Only these observed fields are picked up. Returns None when nothing
    usable is found; never fabricates zeros.
    """
    if not isinstance(value, dict):
        return None
    candidates = []
    if isinstance(value.get("usage"), dict):
        candidates.append(value["usage"])
    candidates.append(value)
    input_keys = ("inputTokens", "input_tokens", "promptTokens", "prompt_tokens")
    output_keys = ("outputTokens", "output_tokens", "completionTokens", "completion_tokens")
    total_keys = ("totalTokens", "total_tokens", "total")
    out: Dict[str, Any] = {}
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        for k in input_keys:
            v = cand.get(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and v >= 0 and "input" not in out:
                out["input"] = int(v)
        for k in output_keys:
            v = cand.get(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and v >= 0 and "output" not in out:
                out["output"] = int(v)
        for k in total_keys:
            v = cand.get(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and v >= 0 and "total" not in out:
                out["total"] = int(v)
        for k, out_k in (("cachedReadTokens", "cached"), ("cached_read_tokens", "cached")):
            v = cand.get(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and v >= 0 and "cached" not in out:
                out["cached"] = int(v)
        # usage_update cumulative counters (observed in artifacts).
        for k, out_k in (("used", "used"), ("size", "size")):
            v = cand.get(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and v >= 0 and out_k not in out:
                out[out_k] = int(v)
        cost = cand.get("cost")
        if isinstance(cost, dict) and "cost" not in out:
            amount = cost.get("amount")
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                out["cost"] = {
                    "amount": amount,
                    "currency": cost.get("currency")
                    if isinstance(cost.get("currency"), str)
                    else None,
                }
    return out or None


def _merge_usage(acc: Dict[str, Any], found: Optional[Dict[str, Any]]) -> None:
    """Keep the max observed value per numeric key (counters are cumulative).

    ``cost`` is replaced with the latest observed value.
    """
    if not found:
        return
    for k, v in found.items():
        if k == "cost":
            acc[k] = v
        elif isinstance(v, (int, float)) and v >= acc.get(k, 0):
            acc[k] = v


@dataclass
class EffortSelection:
    """Resolved ACP thought_level selection for one Worker turn."""

    config_id: Optional[str] = None
    value: Optional[str] = None
    advertised: List[str] = field(default_factory=list)
    unsupported_reason: Optional[str] = None

    @property
    def applied(self) -> bool:
        return self.config_id is not None and self.value is not None


def _flatten_select_values(options: Any) -> List[str]:
    """Return advertised select values from flat or grouped ACP option lists."""
    values: List[str] = []
    if not isinstance(options, list):
        return values
    for entry in options:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if isinstance(value, str) and value:
            values.append(value)
            continue
        values.extend(_flatten_select_values(entry.get("options")))
    return values


def _find_effort_option(config_options: Any) -> Optional[Dict[str, Any]]:
    """Locate the thought_level select option, preferring its category.

    The spec forbids requiring ``category`` for correctness, so OpenCode's
    known option id is accepted as a fallback when no category matches.
    """
    if not isinstance(config_options, list):
        return None
    fallback: Optional[Dict[str, Any]] = None
    for option in config_options:
        if not isinstance(option, dict) or option.get("type") != "select":
            continue
        category = str(option.get("category") or "").strip().lower()
        if category == EFFORT_CATEGORY:
            return option
        option_id = str(option.get("id") or option.get("configId") or "").strip().lower()
        if fallback is None and option_id == EFFORT_OPTION_ID:
            fallback = option
    return fallback


def _select_effort(config_options: Any) -> EffortSelection:
    """Pick an advertised thought_level value in EFFORT_PRIORITY order.

    Returns a selection without a value (and an ``unsupported_reason``) when
    the agent advertises no thought_level option or none of the preferred
    values, so the caller keeps the agent default and records why.
    """
    option = _find_effort_option(config_options)
    if option is None:
        return EffortSelection(unsupported_reason="no thought_level config option advertised")
    advertised = _flatten_select_values(option.get("options"))
    if not advertised:
        return EffortSelection(
            unsupported_reason="thought_level config option advertises no values"
        )
    config_id = option.get("id") or option.get("configId")
    if not isinstance(config_id, str) or not config_id:
        return EffortSelection(
            advertised=advertised,
            unsupported_reason="thought_level config option has no id",
        )
    for candidate in EFFORT_PRIORITY:
        if candidate in advertised:
            return EffortSelection(
                config_id=config_id, value=candidate, advertised=advertised
            )
    return EffortSelection(
        advertised=advertised,
        unsupported_reason="no preferred effort advertised (max/xhigh/high/medium/low)",
    )


class AcpError(Exception):
    """Base exception for ACP protocol/transport errors."""

    pass


class AcpCapabilityMismatchError(AcpError):
    """Raised when server protocol version or required capabilities are missing."""

    pass


class AcpPermissionRejectedError(AcpError):
    """Raised when a permission request cannot be granted by client policy."""

    pass


# ACP v1 session/request_permission option kinds (agentclientprotocol.com).
_PERMISSION_ALLOW_ONCE_KIND = "allow_once"
_PERMISSION_ALLOW_ALWAYS_KIND = "allow_always"
_PERMISSION_REJECT_KINDS = frozenset({"reject_once", "reject_always"})
# Legacy/non-spec option identifiers tolerated for backward compatibility.
_PERMISSION_ALLOW_LEGACY_IDS = frozenset({"allow", "yes", "accept", "permit"})
_PERMISSION_REJECT_LEGACY_IDS = frozenset({"reject", "deny", "no", "cancel", "decline"})


def _permission_option_id(option: Dict[str, Any]) -> Optional[str]:
    value = (
        option.get("optionId")
        or option.get("option_id")
        or option.get("id")
        or option.get("value")
    )
    if value is None:
        return None
    return str(value)


def _permission_option_kind(option: Dict[str, Any]) -> str:
    return str(option.get("kind") or "").strip().lower()


def _select_permission_option(
    options: List[Any],
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Choose an option per least-privilege policy.

    Returns ``(action, option)`` where action is ``"allow"``, ``"reject"`` or
    ``"cancel"``. Spec ``kind`` values are preferred, then legacy identifiers.
    ``allow_once`` is preferred over ``allow_always`` so a persistent permission
    rule is only granted when no single-use option is offered.
    """
    entries = [
        (opt, _permission_option_id(opt), _permission_option_kind(opt))
        for opt in options
        if isinstance(opt, dict)
    ]

    # Spec ``kind`` ordering first so legacy identifiers never outrank a
    # least-privilege spec option that appears later in the list.
    for opt, _opt_id, kind in entries:
        if kind == _PERMISSION_ALLOW_ONCE_KIND:
            return "allow", opt
    for opt, _opt_id, kind in entries:
        if kind == _PERMISSION_ALLOW_ALWAYS_KIND:
            return "allow", opt
    for opt, _opt_id, kind in entries:
        if kind.startswith("allow"):
            return "allow", opt

    # Legacy identifiers and ``outcome`` only after spec kinds.
    for opt, opt_id, kind in entries:
        if not kind and opt_id and opt_id.lower() in _PERMISSION_ALLOW_LEGACY_IDS:
            return "allow", opt
    for opt, _opt_id, _kind in entries:
        if str(opt.get("outcome") or "").strip().lower() == "allow":
            return "allow", opt

    for opt, _opt_id, kind in entries:
        if kind in _PERMISSION_REJECT_KINDS:
            return "reject", opt
    for opt, opt_id, kind in entries:
        if not kind and opt_id and opt_id.lower() in _PERMISSION_REJECT_LEGACY_IDS:
            return "reject", opt

    return "cancel", None


def _permission_record(
    options: List[Any], action: str, option_id: Optional[str]
) -> Dict[str, Any]:
    return {
        "options": [
            {
                "optionId": _permission_option_id(opt),
                "name": opt.get("name") or opt.get("label"),
                "kind": _permission_option_kind(opt) or None,
            }
            for opt in options
            if isinstance(opt, dict)
        ],
        "action": action,
        "selected_option_id": option_id,
    }


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

    def _apply_session_model(
        self, conn: AcpConnection, session_id: str, model: Optional[str] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Pin the resolved OpenCode model on the ACP session.

        Uses ``session/set_config_option`` (configId ``model``); ``model`` is
        the run-frozen session model, and when absent or not allowlisted it
        falls back to the configured default. Raises AcpError on rejection: a
        misconfigured model name must fail the turn instead of silently
        running on the agent default. Returns the model sent and the
        ``configOptions`` advertised after the change (the source for effort
        selection).
        """
        from obsidian_ai_hub.utils.config import (
            get_available_coding_models,
            resolve_effective_coding_model,
        )

        candidate = (model or "").strip()
        if candidate and candidate not in get_available_coding_models():
            raise AcpError(
                f"OpenCode model '{candidate}' is not in the configured model list "
                "(coding.acp.opencode_models); refusing to run on an unknown model."
            )
        resolved = resolve_effective_coding_model(candidate or None) if candidate else (CODING_OPENCODE_MODEL or "").strip()
        if not resolved:
            raise AcpError(
                "OpenCode model is not configured (coding.acp.opencode_model / "
                "CODING_OPENCODE_MODEL); refusing to run on an unknown model."
            )
        model = resolved
        try:
            result = conn.request(
                "session/set_config_option",
                {"sessionId": session_id, "configId": "model", "value": model},
                timeout=15.0,
            )
        except AcpError as exc:
            raise AcpError(
                f"Failed to set OpenCode model '{model}' on ACP session "
                f"'{session_id}' via session/set_config_option: {exc}. "
                "Check coding.acp.opencode_model / CODING_OPENCODE_MODEL."
            ) from exc
        logger.info("ACP session '%s' model set to '%s'.", session_id, model)
        config_options = result.get("configOptions") if isinstance(result, dict) else None
        if not isinstance(config_options, list):
            config_options = []
        return model, config_options

    def _apply_session_effort(
        self, conn: AcpConnection, session_id: str, selection: EffortSelection
    ) -> None:
        """Set the advertised thought_level value before prompting.

        No applicable advertised value is not an error: the agent default is
        kept and reported through diagnostics. A rejected set is an error so
        the turn fails instead of silently falling back to another effort.
        """
        if not selection.applied:
            logger.info(
                "ACP session '%s' runs with the agent default effort (%s).",
                session_id,
                selection.unsupported_reason,
            )
            return
        try:
            conn.request(
                "session/set_config_option",
                {
                    "sessionId": session_id,
                    "configId": selection.config_id,
                    "value": selection.value,
                },
                timeout=15.0,
            )
        except AcpError as exc:
            raise AcpError(
                f"Failed to set OpenCode effort '{selection.value}' on ACP session "
                f"'{session_id}' (configId '{selection.config_id}'): {exc}."
            ) from exc
        logger.info("ACP session '%s' effort set to '%s'.", session_id, selection.value)

    def _handle_permission_request(
        self,
        req: Dict[str, Any],
        conn: AcpConnection,
        records: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Handle a session/request_permission RPC request from the ACP agent.

        Delegated technical work is not escalated to HITL (see
        docs/acp/permission-hitl-contract.md D3). Per least-privilege policy an
        ``allow_once`` option is preferred, then ``allow_always``, then any
        allow-kind option. A request that offers no allow option is declined:
        the client replies with a spec-shaped ``selected`` reject option when
        one exists, otherwise ``cancelled``, and raises
        ``AcpPermissionRejectedError`` so the turn fails instead of silently
        substituting another mode.

        Responses follow the ACP v1 spec: ``{"outcome": {"outcome":
        "selected", "optionId": ...}}`` or ``{"outcome": {"outcome":
        "cancelled"}}``. The chosen request/response is appended to ``records``
        for run diagnostics.
        """
        rid = req.get("id")
        params = req.get("params") or {}
        options = params.get("options") or []
        if not isinstance(options, list):
            options = []

        action, option = _select_permission_option(options)
        option_id = _permission_option_id(option) if option is not None else None
        if action == "allow" and option_id is None:
            # An allow option with no resolvable id cannot be selected in a
            # spec response; record and reply as a decline so diagnostics match.
            action = "cancel"
        record = _permission_record(options, action, option_id)
        if records is not None:
            records.append(record)

        if action == "allow" and option_id is not None and rid is not None:
            conn.respond(rid, {"outcome": {"outcome": "selected", "optionId": option_id}})
            return record

        if action == "reject" and option_id is not None and rid is not None:
            conn.respond(rid, {"outcome": {"outcome": "selected", "optionId": option_id}})
            raise AcpPermissionRejectedError(
                f"ACP permission rejected by client policy: options {options}"
            )

        if rid is not None:
            conn.respond(rid, {"outcome": {"outcome": "cancelled"}})
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
        model: Optional[str] = None,
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
        sent_model: Optional[str] = None
        effort = EffortSelection()
        permissions: List[Dict[str, Any]] = []

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

            # Pin the OpenCode-side model via ACP config options before
            # prompting (per-prompt model params are ignored by OpenCode; fail
            # the turn on rejection so a misconfigured model surfaces instead
            # of silently running on the agent default). The agent's response
            # advertises the efforts available for that model; apply the best
            # preferred one before prompting, or keep the agent default when
            # none is advertised.
            sent_model, model_config_options = self._apply_session_model(
                conn, curr_session_id, model
            )
            effort = _select_effort(model_config_options)
            self._apply_session_effort(conn, curr_session_id, effort)

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
            worker_tool_terminal: Dict[str, str] = {}
            usage_acc: Dict[str, Any] = {}

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
                        self._handle_permission_request(client_req, conn, permissions)
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
                        nested = params.get("update")
                        if not isinstance(nested, dict):
                            nested = None
                        kind = (
                            str(nested.get("sessionUpdate"))
                            if nested and nested.get("sessionUpdate")
                            else None
                        )

                        # Only assistant message text becomes the worker output.
                        # Thought chunks are delivered via on_update_callback for
                        # separate display and must not leak into the final worker
                        # message. Flat (non-spec) shapes carry no kind and are
                        # treated as assistant message text.
                        if kind in (None, "agent_message_chunk"):
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
                            if nested is not None:
                                texts.extend(_extract_content_text(nested.get("content")))
                            flat_part = params.get("part")
                            if (
                                isinstance(flat_part, dict)
                                and flat_part.get("type") == "text"
                                and isinstance(flat_part.get("text"), str)
                            ):
                                texts.append(flat_part["text"])
                            output_chunks.extend(texts)

                        kind_key = kind if kind else "flat"
                        update_kinds[kind_key] = update_kinds.get(kind_key, 0) + 1

                        if kind in ("tool_call", "tool_call_update") and isinstance(nested, dict):
                            tc_id = nested.get("toolCallId") or nested.get("tool_call_id")
                            raw_status = str(nested.get("status") or "")
                            # Terminal Worker tool states only; pending/in_progress
                            # must not inflate the count and each toolCallId is
                            # counted once (no double counting across updates).
                            if tc_id and raw_status in ("completed", "failed"):
                                worker_tool_terminal[str(tc_id)] = raw_status
                        if kind == "usage_update" and isinstance(nested, dict):
                            _merge_usage(usage_acc, _extract_usage_numbers(nested))
                            for uk in ("usage", "tokens", "tokenUsage"):
                                _merge_usage(usage_acc, _extract_usage_numbers(nested.get(uk)))

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
                    _merge_usage(usage_acc, _extract_usage_numbers(res_data))
                    _merge_usage(usage_acc, _extract_usage_numbers(res_data.get("usage")))

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
                "transport": "acp",
                "acp_session_id": curr_session_id,
                "acp_version": init_meta.get("protocol_version"),
                "acp_profile_id": self.profile.profile_id,
                "acp_model": sent_model,
                "acp_effort": effort.value,
                "acp_effort_advertised": effort.advertised or None,
                "acp_effort_unsupported_reason": effort.unsupported_reason,
                "acp_agent": agent_info,
                "acp_capabilities": init_meta.get("capabilities"),
                "stop_reason": stop_reason,
                "session_recreated": session_recreated,
                "stderr_snippet": stderr_str[:500] if stderr_str else None,
                "elicitations": elicitations,
                "permissions": permissions,
                "update_kinds": update_kinds,
                "worker_tool_call_count": len(worker_tool_terminal),
                "worker_tool_failure_count": sum(
                    1 for s in worker_tool_terminal.values() if s == "failed"
                ),
                "usage": dict(usage_acc) or None,
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
                    "transport": "acp",
                    "acp_session_id": curr_session_id or acp_session_id,
                    "acp_profile_id": self.profile.profile_id,
                    "acp_model": sent_model,
                    "acp_effort": effort.value,
                    "acp_effort_advertised": effort.advertised or None,
                    "acp_effort_unsupported_reason": effort.unsupported_reason,
                    "error": str(exc),
                    "permissions": permissions,
                },
            )
