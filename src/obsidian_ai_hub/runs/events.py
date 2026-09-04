"""Shared SSE event helpers: text aggregation, formatting, cursor parsing."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

TEXT_AGGREGATE_MAX_MS = 250
TEXT_AGGREGATE_MAX_BYTES = 4096


class TextAggregator:
    """Aggregate token deltas into ~250ms / ~4KB text_append events.

    SQLite writes are not done per token. The worker buffers deltas and
    flushes when either threshold is reached. Only the uncommitted buffer
    can be lost on crash; the run then becomes interrupted.
    """

    def __init__(
        self,
        max_ms: int = TEXT_AGGREGATE_MAX_MS,
        max_bytes: int = TEXT_AGGREGATE_MAX_BYTES,
        clock: Any = None,
    ) -> None:
        self._max_ms = max_ms
        self._max_bytes = max_bytes
        self._clock = clock or time.monotonic
        self._buf: list[str] = []
        self._buf_bytes = 0
        self._started_at: Optional[float] = None

    def add(self, delta: str) -> Optional[str]:
        """Add a delta; return aggregated text when thresholds are hit."""
        if not delta:
            return None
        if self._started_at is None:
            self._started_at = self._clock()
        self._buf.append(delta)
        self._buf_bytes += len(delta.encode("utf-8"))
        if self._buf_bytes >= self._max_bytes:
            return self.flush()
        elapsed_ms = (self._clock() - self._started_at) * 1000.0
        if elapsed_ms >= self._max_ms:
            return self.flush()
        return None

    def flush(self) -> Optional[str]:
        if not self._buf:
            self._started_at = None
            return None
        out = "".join(self._buf)
        self._buf = []
        self._buf_bytes = 0
        self._started_at = None
        return out

    @property
    def pending(self) -> str:
        return "".join(self._buf)


def format_sse(event_id: int, payload: dict[str, Any]) -> str:
    """Format a persisted event row as SSE with id: (at-least-once replay)."""
    data = json.dumps(payload, ensure_ascii=False)
    return f"id: {event_id}\ndata: {data}\n\n"


def heartbeat_sse() -> str:
    return ": heartbeat\n\n"


def parse_last_event_id(value: Any) -> int:
    """Parse Last-Event-ID header/query into a cursor (default 0)."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value if value >= 0 else 0
    text = str(value).strip()
    if not text:
        return 0
    try:
        parsed = int(text)
    except (ValueError, TypeError):
        return 0
    return parsed if parsed >= 0 else 0


def is_terminal_event(event_type: str, payload: dict[str, Any]) -> bool:
    if event_type in ("done", "error", "cancelled"):
        return True
    # Legacy coding payloads use {"event": "done"/"error"/"cancelled"} inside data.
    legacy = str(payload.get("event") or payload.get("type") or "")
    return legacy in ("done", "error", "cancelled")
