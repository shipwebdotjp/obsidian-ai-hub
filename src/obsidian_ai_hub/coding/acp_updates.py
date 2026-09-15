"""Normalize ACP ``session/update`` notifications into coding run events.

The ACP client backend invokes :meth:`AcpUpdateStreamer.handle` for every
``session/update`` notification on the worker thread that owns the ACP
subprocess. Events are persisted through the coding run event log so the Web UI
can replay and follow them over SSE.

Raw ACP payloads (``rawInput``/``rawOutput``) may carry secrets or very large
values, so only bounded and redacted fields are persisted. Secret detection is
a key-name heuristic; it is not a guarantee for arbitrary free text.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional

from obsidian_ai_hub.coding import store
from obsidian_ai_hub.runs.events import TextAggregator

logger = logging.getLogger(__name__)

MAX_STRING_CHARS = 2000
MAX_PAYLOAD_BYTES = 8192
MAX_LIST_ITEMS = 50
MAX_DEPTH = 6
MAX_LOCATIONS = 20
REDACTED = "[redacted]"

_SENSITIVE_KEY_HINTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
)

# ACP tool call status -> UI status vocabulary (CodingLiveToolCall.status).
_TOOL_STATUS_MAP = {
    "pending": "preparing",
    "in_progress": "running",
    "completed": "succeeded",
    "failed": "failed",
}


def _truncate(text: str, limit: int = MAX_STRING_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[truncated {len(text) - limit} chars]"


def _is_sensitive_key(key: Any) -> bool:
    if key is None:
        return False
    lowered = str(key).lower()
    return any(hint in lowered for hint in _SENSITIVE_KEY_HINTS)


def sanitize(value: Any, *, key: Any = None, depth: int = 0) -> Any:
    """Return a bounded, redacted copy of an ACP raw value."""
    if _is_sensitive_key(key):
        return REDACTED
    if depth > MAX_DEPTH:
        return "[truncated]"
    if isinstance(value, str):
        return _truncate(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        items = list(value.items())[:MAX_LIST_ITEMS]
        return {
            str(k): sanitize(v, key=k, depth=depth + 1) for k, v in items
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(v, depth=depth + 1) for v in list(value)[:MAX_LIST_ITEMS]]
    return _truncate(str(value))


def _bound_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Final size guard so a pathological payload cannot bloat the event log.

    Routing keys (event correlation/idempotency) are kept even when the bulk
    payload is dropped, so replay and frontend de-duplication still work.
    """
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded.encode("utf-8")) <= MAX_PAYLOAD_BYTES:
        return payload
    truncated: Dict[str, Any] = {"truncated": True, "preview": _truncate(encoded)}
    for key in ("tool_call_id", "phase", "phase_turn", "attempt"):
        if key in payload:
            truncated[key] = payload[key]
    return truncated


def _content_text(content: Any) -> str:
    """Extract text from an ACP tool call content value."""
    parts: List[str] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            inner = item.get("content")
            if isinstance(inner, dict) and isinstance(inner.get("text"), str):
                parts.append(inner["text"])
            elif isinstance(item.get("text"), str):
                parts.append(item["text"])
    elif isinstance(content, dict) and isinstance(content.get("text"), str):
        parts.append(content["text"])
    return "\n".join(part for part in parts if part)


def _flat_text(params: Dict[str, Any]) -> str:
    """Extract assistant text from non-spec (flat) update shapes."""
    parts: List[str] = []
    if isinstance(params.get("text"), str):
        parts.append(params["text"])
    content = params.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, dict) and isinstance(content.get("text"), str):
        parts.append(content["text"])
    part = params.get("part")
    if (
        isinstance(part, dict)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    ):
        parts.append(part["text"])
    return "".join(parts)


class AcpUpdateStreamer:
    """Classify ACP updates and persist them as coding run events.

    ``handle`` is called from the ACP worker thread; ``flush`` is called after
    the turn returns. Both are safe to call concurrently because text
    aggregation is guarded by a lock.
    """

    def __init__(
        self,
        *,
        run_id: str,
        phase: Optional[str] = None,
        phase_turn: Optional[int] = None,
        attempt: Optional[int] = None,
    ):
        self._run_id = run_id
        self._phase = phase
        self._phase_turn = phase_turn
        self._attempt = attempt
        self._message_aggregator = TextAggregator()
        self._thought_aggregator = TextAggregator()
        self._lock = threading.Lock()

    def handle(self, params: Any) -> None:
        try:
            self._handle(params)
        except Exception:
            logger.exception("Failed to persist ACP update for run %s", self._run_id)

    def _handle(self, params: Any) -> None:
        if not isinstance(params, dict):
            return
        update = params.get("update")
        if not isinstance(update, dict):
            # Flat (non-spec) shape: text only, treated as assistant message.
            text = _flat_text(params)
            if text:
                self._append_text("text_append", self._message_aggregator, text)
            return

        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            text = "".join(_extract_text_parts(update.get("content")))
            if text:
                self._append_text("text_append", self._message_aggregator, text)
        elif kind == "agent_thought_chunk":
            text = "".join(_extract_text_parts(update.get("content")))
            if text:
                self._append_text(
                    "acp_thought_append", self._thought_aggregator, text
                )
        elif kind == "tool_call":
            self._flush_text()
            self._append("acp_tool_call", self._tool_payload(update))
        elif kind == "tool_call_update":
            self._flush_text()
            self._append(
                "acp_tool_call_update", self._tool_payload(update, include_result=True)
            )
        elif kind == "plan":
            self._flush_text()
            entries = sanitize(update.get("entries"))
            self._append(
                "acp_plan",
                {"entries": entries if isinstance(entries, list) else []},
            )
        # usage_update / available_commands_update / unknown: not streamed.

    def _append_text(
        self, event_type: str, aggregator: TextAggregator, delta: str
    ) -> None:
        with self._lock:
            aggregated = aggregator.add(delta)
        if aggregated:
            self._append(event_type, {"delta": aggregated})

    def _tool_payload(
        self, update: Dict[str, Any], *, include_result: bool = False
    ) -> Dict[str, Any]:
        tool_call_id = update.get("toolCallId") or update.get("tool_call_id") or ""
        title = update.get("title") or update.get("kind") or ""
        raw_status = update.get("status")
        payload: Dict[str, Any] = {
            "tool_call_id": str(tool_call_id),
            "tool_name": str(title),
            "kind": update.get("kind"),
            "status": _TOOL_STATUS_MAP.get(str(raw_status), raw_status),
            "args": sanitize(update.get("rawInput"))
            if update.get("rawInput") is not None
            else {},
        }
        locations = update.get("locations")
        if isinstance(locations, list):
            paths = [
                loc.get("path")
                for loc in locations[:MAX_LOCATIONS]
                if isinstance(loc, dict) and isinstance(loc.get("path"), str)
            ]
            if paths:
                payload["locations"] = [{"path": _truncate(p)} for p in paths]
        if include_result:
            result = _content_text(update.get("content"))
            if not result:
                raw_output = update.get("rawOutput")
                if isinstance(raw_output, dict) and isinstance(
                    raw_output.get("output"), str
                ):
                    result = raw_output["output"]
            if result:
                payload["result"] = _truncate(result)
            if update.get("error"):
                payload["error"] = _truncate(str(update.get("error")))
        return payload

    def _append(self, event_type: str, payload: Dict[str, Any]) -> None:
        enriched = dict(payload)
        enriched.setdefault("phase", self._phase)
        enriched.setdefault("phase_turn", self._phase_turn)
        enriched.setdefault("attempt", self._attempt)
        bounded = _bound_payload(enriched)
        store.append_run_event(self._run_id, event_type, bounded)

    def _flush_text(self) -> None:
        """Persist buffered text so it keeps its chronological position."""
        with self._lock:
            pending_message = self._message_aggregator.flush()
            pending_thought = self._thought_aggregator.flush()
        for event_type, delta in (
            ("text_append", pending_message),
            ("acp_thought_append", pending_thought),
        ):
            if delta:
                self._append(event_type, {"delta": delta})

    def flush(self) -> None:
        """Persist any uncommitted aggregated text (call after the turn)."""
        try:
            self._flush_text()
        except Exception:
            logger.exception("Failed to flush ACP text for run %s", self._run_id)


def _extract_text_parts(content: Any) -> List[str]:
    """Extract text from an ACP update content value (dict or list)."""
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
