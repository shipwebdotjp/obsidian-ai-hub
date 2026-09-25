"""Collect CLI and LLM failure history into fingerprint-grouped findings."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils import config

_MAX_QUERY_ROWS = 500
_MAX_EXCEPTION_MESSAGES = 5
_MAX_TRACEBACKS = 3
_MAX_RELATED_LLM_FAILURES = 5

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_NUMBER_RE = re.compile(r"\d+")
_WHITESPACE_RE = re.compile(r"\s+")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(
        r"(?i)\b(token|api[_-]?key|apikey|password|secret|authorization)\b[\"']?\s*[:=]\s*[\"']?[^\s\"',;]{6,}"
    ),
    re.compile(
        r"(?i)--(token|api[_-]?key|apikey|password|secret)(=|\s+)\S+"
    ),
)


def normalize_message(message: str) -> str:
    """Normalize an exception message so varying ids/counts share a fingerprint."""
    text = (message or "").strip().lower()
    text = _UUID_RE.sub("<uuid>", text)
    text = _HEX_RE.sub("<hex>", text)
    text = _NUMBER_RE.sub("<n>", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def compute_fingerprint(
    kind: str, label: str, exception_type: str, exception_message: str
) -> str:
    parts = [
        kind,
        (label or "").strip(),
        (exception_type or "").strip(),
        normalize_message(exception_message),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def redact_secrets(text: str) -> str:
    redacted = text or ""
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _trim(text: Optional[str], limit: int) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_command_rows(conn, cutoff: str, stale_cutoff: str) -> List[Any]:
    failed = conn.execute(
        """
        SELECT run_id, command, exception_type, exception_message, traceback,
               started_at, finished_at, status
        FROM command_runs
        WHERE status = 'failed' AND started_at >= ?
        ORDER BY started_at DESC
        LIMIT ?;
        """,
        (cutoff, _MAX_QUERY_ROWS),
    ).fetchall()
    stale = conn.execute(
        """
        SELECT run_id, command, exception_type, exception_message, traceback,
               started_at, finished_at, status
        FROM command_runs
        WHERE status = 'running' AND started_at < ?
        ORDER BY started_at DESC
        LIMIT ?;
        """,
        (stale_cutoff, _MAX_QUERY_ROWS),
    ).fetchall()
    return failed + stale


def _fetch_llm_rows(conn, cutoff: str, stale_cutoff: str) -> List[Any]:
    failed = conn.execute(
        """
        SELECT call_id, run_id, provider, model, exception_type, exception_message,
               traceback, started_at, finished_at, status
        FROM llm_call_logs
        WHERE status = 'failed' AND started_at >= ?
        ORDER BY started_at DESC
        LIMIT ?;
        """,
        (cutoff, _MAX_QUERY_ROWS),
    ).fetchall()
    stale = conn.execute(
        """
        SELECT call_id, run_id, provider, model, exception_type, exception_message,
               traceback, started_at, finished_at, status
        FROM llm_call_logs
        WHERE status = 'running' AND started_at < ?
        ORDER BY started_at DESC
        LIMIT ?;
        """,
        (stale_cutoff, _MAX_QUERY_ROWS),
    ).fetchall()
    return failed + stale


def _command_record(row: Any) -> Dict[str, Any]:
    stale = row["status"] == "running"
    return {
        "run_id": row["run_id"],
        "label": redact_secrets(row["command"] or "(unknown command)"),
        "exception_type": row["exception_type"]
        or ("StaleRunning" if stale else "UnknownError"),
        "exception_message": row["exception_message"]
        or ("No terminal status recorded" if stale else ""),
        "traceback": row["traceback"],
        "started_at": row["started_at"],
        "last_seen_at": row["finished_at"] or row["started_at"],
    }


def _llm_record(row: Any) -> Dict[str, Any]:
    stale = row["status"] == "running"
    provider = row["provider"] or "unknown"
    model = row["model"] or "unknown"
    return {
        "call_id": row["call_id"],
        "run_id": row["run_id"],
        "label": redact_secrets(f"{provider}/{model}"),
        "provider": provider,
        "model": model,
        "exception_type": row["exception_type"]
        or ("StaleRunning" if stale else "UnknownError"),
        "exception_message": row["exception_message"]
        or ("No terminal status recorded" if stale else ""),
        "traceback": row["traceback"],
        "started_at": row["started_at"],
        "last_seen_at": row["finished_at"] or row["started_at"],
    }


def _new_group(kind: str, label: str, exception_type: str) -> Dict[str, Any]:
    return {
        "fingerprint": "",
        "kind": kind,
        "label": label,
        "exception_type": exception_type,
        "occurrence_count": 0,
        "first_seen_at": None,
        "last_seen_at": None,
        "run_ids": [],
        "call_ids": [],
        "exception_messages": [],
        "tracebacks": [],
        "related_llm_failures": [],
    }


def _update_bounds(group: Dict[str, Any], record: Dict[str, Any]) -> None:
    started = record.get("started_at")
    seen = record.get("last_seen_at") or started
    if started and (group["first_seen_at"] is None or started < group["first_seen_at"]):
        group["first_seen_at"] = started
    if seen and (group["last_seen_at"] is None or seen > group["last_seen_at"]):
        group["last_seen_at"] = seen


def _command_groups(
    command_records: List[Dict[str, Any]], related_llm_by_run: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for record in command_records:
        fingerprint = compute_fingerprint(
            "command",
            record["label"],
            record["exception_type"] or "",
            redact_secrets(record["exception_message"] or ""),
        )
        group = groups.get(fingerprint)
        if group is None:
            group = _new_group("command", record["label"], record["exception_type"])
            group["fingerprint"] = fingerprint
            groups[fingerprint] = group
        group["occurrence_count"] += 1
        _update_bounds(group, record)
        if record["run_id"] not in group["run_ids"]:
            group["run_ids"].append(record["run_id"])
        message = _trim(redact_secrets(record["exception_message"]), 1000)
        if message and message not in group["exception_messages"]:
            group["exception_messages"].append(message)
        traceback = _trim(
            redact_secrets(record["traceback"]),
            config.SYSTEM_MAINTENANCE_MAX_TRACEBACK_CHARS,
        )
        if traceback and len(group["tracebacks"]) < _MAX_TRACEBACKS:
            group["tracebacks"].append(traceback)
        for llm in related_llm_by_run.get(record["run_id"], []):
            if len(group["related_llm_failures"]) >= _MAX_RELATED_LLM_FAILURES:
                break
            group["related_llm_failures"].append(llm)
    return groups


def _standalone_llm_groups(
    llm_records: List[Dict[str, Any]], bundled_call_ids: set
) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for record in llm_records:
        if record["call_id"] in bundled_call_ids:
            continue
        fingerprint = compute_fingerprint(
            "llm",
            record["label"],
            record["exception_type"] or "",
            redact_secrets(record["exception_message"] or ""),
        )
        group = groups.get(fingerprint)
        if group is None:
            group = _new_group("llm", record["label"], record["exception_type"])
            group["fingerprint"] = fingerprint
            groups[fingerprint] = group
        group["occurrence_count"] += 1
        _update_bounds(group, record)
        if record["call_id"] not in group["call_ids"]:
            group["call_ids"].append(record["call_id"])
        message = _trim(redact_secrets(record["exception_message"]), 1000)
        if message and message not in group["exception_messages"]:
            group["exception_messages"].append(message)
        traceback = _trim(
            redact_secrets(record["traceback"]),
            config.SYSTEM_MAINTENANCE_MAX_TRACEBACK_CHARS,
        )
        if traceback and len(group["tracebacks"]) < _MAX_TRACEBACKS:
            group["tracebacks"].append(traceback)
    return groups


def collect_failure_findings(
    window_hours: Optional[int] = None,
    *,
    now: Optional[datetime] = None,
    stale_running_hours: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Group failed CLI runs and LLM calls in the window by fingerprint.

    LLM failures whose ``run_id`` points at a failed command run are attached
    as evidence to that command finding instead of becoming a separate one.
    """
    current = now or _now()
    window = int(
        window_hours if window_hours is not None else config.SYSTEM_MAINTENANCE_WINDOW_HOURS
    )
    stale = int(
        stale_running_hours
        if stale_running_hours is not None
        else config.SYSTEM_MAINTENANCE_STALE_RUNNING_HOURS
    )
    cutoff = (current - timedelta(hours=window)).isoformat()
    stale_cutoff = (current - timedelta(hours=stale)).isoformat()

    conn = get_db_connection()
    try:
        command_records = [_command_record(r) for r in _fetch_command_rows(conn, cutoff, stale_cutoff)]
        llm_records = [_llm_record(r) for r in _fetch_llm_rows(conn, cutoff, stale_cutoff)]
    finally:
        conn.close()

    command_run_ids = {r["run_id"] for r in command_records}
    related_llm_by_run: Dict[str, List[Dict[str, Any]]] = {}
    bundled_call_ids = set()
    for record in llm_records:
        if record["run_id"] and record["run_id"] in command_run_ids:
            related_llm_by_run.setdefault(record["run_id"], []).append(
                {
                    "call_id": record["call_id"],
                    "provider": record["provider"],
                    "model": record["model"],
                    "exception_type": record["exception_type"],
                    "exception_message": _trim(
                        redact_secrets(record["exception_message"]), 500
                    ),
                }
            )
            bundled_call_ids.add(record["call_id"])

    groups = _command_groups(command_records, related_llm_by_run)
    groups.update(_standalone_llm_groups(llm_records, bundled_call_ids))

    findings = []
    for group in groups.values():
        group["exception_messages"] = group["exception_messages"][:_MAX_EXCEPTION_MESSAGES]
        findings.append(group)
    findings.sort(
        key=lambda g: (g["occurrence_count"], g["last_seen_at"] or ""), reverse=True
    )
    return findings
