"""ACP PoC stdio JSON-RPC harness (stdlib only, no app imports, no DB).

Separation for Phase 1 reuse:
  - AcpConnection: transport only (spawn, NDJSON encode/decode, id correlation,
    timeout, process-group cleanup, orphan check, secret redaction).
  - Scenario logic lives in run_poc.py; provider differences live in profiles/.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def load_dotenv_values(path: str | Path) -> dict[str, str]:
    """Parse KEY=VALUE lines (no shell expansion, no export to os.environ)."""
    values: dict[str, str] = {}
    p = Path(path).expanduser()
    if not p.exists():
        return values
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            values[key] = val
    return values


class Redactor:
    """Replace secret values with a placeholder in any recorded/logged text."""

    def __init__(self, secrets: dict[str, str], placeholder: str = "***REDACTED***"):
        self.placeholder = placeholder
        # Longest first so overlapping values redact correctly.
        self._needles = sorted(
            {v for v in secrets.values() if v and len(v) >= 4},
            key=len,
            reverse=True,
        )

    def __call__(self, text: str) -> str:
        for needle in self._needles:
            text = text.replace(needle, self.placeholder)
        return text


@dataclass
class AcpMessage:
    direction: str  # "sent" | "received"
    payload: dict[str, Any]
    t_ms: int = 0


class AcpError(Exception):
    pass


class AcpConnection:
    """One stdio ACP agent subprocess + JSON-RPC correlation."""

    def __init__(
        self,
        argv: list[str],
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
        redactor: Optional[Redactor] = None,
    ):
        self.argv = argv
        self.env = env if env is not None else os.environ.copy()
        self.cwd = cwd
        self.redactor = redactor or (lambda s: s)
        self.proc: Optional[subprocess.Popen] = None
        self.pgid: Optional[int] = None
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._responses: dict[int, queue.Queue] = {}
        self._resp_lock = threading.Lock()
        self._notifications: queue.Queue = queue.Queue()
        self._client_requests: queue.Queue = queue.Queue()
        self.stdout_log: list[str] = []  # raw stdout lines (redacted on export)
        self.stderr_chunks: list[str] = []
        self.non_json_stdout: list[str] = []
        self._threads: list[threading.Thread] = []
        self._closed = False

    # -- lifecycle ---------------------------------------------------------

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
            bufsize=1,  # line buffered
            start_new_session=True,
        )
        assert self.proc.pid is not None
        self.pgid = os.getpgid(self.proc.pid)
        t_out = threading.Thread(target=self._read_stdout, daemon=True)
        t_err = threading.Thread(target=self._read_stderr, daemon=True)
        t_out.start()
        t_err.start()
        self._threads = [t_out, t_err]

    @property
    def pid(self) -> Optional[int]:
        return self.proc.pid if self.proc else None

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        try:
            for line in iter(self.proc.stdout.readline, ""):
                text = line.rstrip("\n")
                if not text.strip():
                    continue
                self.stdout_log.append(text)
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    self.non_json_stdout.append(text)
                    continue
                if not isinstance(msg, dict):
                    self.non_json_stdout.append(text)
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
                self.stderr_chunks.append(line.rstrip("\n"))
        finally:
            try:
                self.proc.stderr.close()
            except Exception:
                pass

    # -- sending -----------------------------------------------------------

    def next_id(self) -> int:
        with self._id_lock:
            self._next_id += 1
            return self._next_id

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        data = json.dumps(payload, ensure_ascii=False)
        self.proc.stdin.write(data + "\n")
        self.proc.stdin.flush()

    def request(
        self, method: str, params: dict[str, Any], timeout: float = 60.0
    ) -> dict[str, Any]:
        rid = self.next_id()
        q: queue.Queue = queue.Queue()
        with self._resp_lock:
            self._responses[rid] = q
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            try:
                return q.get(timeout=timeout)
            except queue.Empty:
                raise AcpError(f"timeout waiting for response to {method} (id={rid})")
        finally:
            with self._resp_lock:
                self._responses.pop(rid, None)

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def respond(self, rid: int, result: Any) -> None:
        self._send({"jsonrpc": "2.0", "id": rid, "result": result})

    def respond_error(self, rid: int, code: int, message: str) -> None:
        self._send(
            {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}
        )

    def drain_notifications(self) -> list[dict[str, Any]]:
        out = []
        while True:
            try:
                out.append(self._notifications.get_nowait())
            except queue.Empty:
                return out

    def drain_client_requests(self) -> list[dict[str, Any]]:
        out = []
        while True:
            try:
                out.append(self._client_requests.get_nowait())
            except queue.Empty:
                return out

    def wait_for_response(self, rid: int, timeout: float) -> Optional[dict[str, Any]]:
        with self._resp_lock:
            q = self._responses.get(rid)
        if q is None:
            return None
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None

    def send_request_async(self, method: str, params: dict[str, Any]) -> int:
        """Send a request without blocking; caller correlates via wait_for_response."""
        rid = self.next_id()
        q: queue.Queue = queue.Queue()
        with self._resp_lock:
            self._responses[rid] = q
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return rid

    # -- teardown ----------------------------------------------------------

    def terminate(self, grace_s: float = 5.0) -> dict[str, Any]:
        """SIGTERM the process group, escalate to SIGKILL, report orphans."""
        report: dict[str, Any] = {
            "exitCode": None,
            "signalled": False,
            "orphans": [],
        }
        if not self.proc or self._closed:
            return report
        self._closed = True
        try:
            if self.proc.poll() is None and self.pgid is not None:
                os.killpg(self.pgid, signal.SIGTERM)
                report["signalled"] = True
        except (ProcessLookupError, PermissionError):
            pass
        try:
            report["exitCode"] = self.proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            try:
                if self.pgid is not None:
                    os.killpg(self.pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            report["exitCode"] = self.proc.wait(timeout=10.0)
        # Close stdin so a hung agent cannot block; join readers briefly.
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        for t in self._threads:
            t.join(timeout=2.0)
        report["orphans"] = self.check_orphans()
        return report

    def check_orphans(self) -> list[int]:
        """PIDs still alive in our process group (best effort, pgrep)."""
        if self.pgid is None:
            return []
        try:
            proc = subprocess.run(
                ["pgrep", "-g", str(self.pgid)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return []
        if proc.returncode != 0:
            return []
        found = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                found.append(int(line))
        return found

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # -- artifact export ---------------------------------------------------

    def redacted_stderr(self) -> str:
        return self.redactor("\n".join(self.stderr_chunks))

    def redacted_stdout_log(self) -> list[str]:
        return [self.redactor(line) for line in self.stdout_log]


@dataclass
class ScenarioRecorder:
    """Collect sent/received messages + notes, export redacted JSON artifact."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    _t0: float = field(default_factory=time.monotonic)

    def _now_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def sent(self, payload: dict[str, Any]) -> None:
        self.entries.append(
            {"t_ms": self._now_ms(), "direction": "sent", "payload": payload}
        )

    def received(self, payload: dict[str, Any]) -> None:
        self.entries.append(
            {"t_ms": self._now_ms(), "direction": "received", "payload": payload}
        )

    def note(self, text: str) -> None:
        self.entries.append({"t_ms": self._now_ms(), "direction": "note", "text": text})

    def export(self, redactor: Redactor) -> list[dict[str, Any]]:
        out = []
        for e in self.entries:
            if e.get("direction") == "note":
                out.append({**e, "text": redactor(e["text"])})
            else:
                raw = json.dumps(e["payload"], ensure_ascii=False)
                out.append(
                    {
                        **e,
                        "payload": json.loads(redactor(raw)),
                    }
                )
        return out
