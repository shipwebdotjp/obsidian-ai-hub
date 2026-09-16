"""Accumulate per-run ACP worker token usage across attempts.

ACP exposes two kinds of usage numbers (verified against
``docs/acp/artifacts``):

- ``session/prompt`` result ``usage``: per-attempt turn totals
  (``input``/``output``/``total``/``cached``). These are added up, because a
  single user prompt may fan out into several worker attempts inside one run.
- ``session/update`` ``usage_update``: session-cumulative counters
  (``used``/``size``/``cost``). ``used``/``size`` are context-window
  snapshots, so only the maximum observed value is kept.

The accumulated block is stored under ``usage_cumulative`` in a run's
diagnostics so the UI can show a run total even when the worker ran several
attempts, while the legacy per-attempt ``usage`` key is preserved untouched.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_ADDITIVE_KEYS = ("input", "output", "total", "cached")
_MAX_KEYS = ("used", "size")


def new_usage_totals() -> Dict[str, Any]:
    """Return a zeroed accumulation state for one run."""
    return {
        "input": 0,
        "output": 0,
        "total": 0,
        "cached": 0,
        "used_max": 0,
        "size_max": 0,
        "cost": {"amount": 0.0, "currency": None},
    }


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def accumulate_usage(totals: Dict[str, Any], usage: Optional[Dict[str, Any]]) -> None:
    """Fold one attempt's ``usage`` into ``totals`` in place (no-op when absent)."""
    if not isinstance(usage, dict):
        return
    for key in _ADDITIVE_KEYS:
        value = _number(usage.get(key))
        if value is not None and value >= 0:
            totals[key] = totals.get(key, 0) + int(value)
    for key in _MAX_KEYS:
        value = _number(usage.get(key))
        if value is not None and value >= 0:
            current = totals.get(f"{key}_max", 0)
            totals[f"{key}_max"] = max(current, int(value))
    cost = usage.get("cost")
    if isinstance(cost, dict):
        amount = _number(cost.get("amount"))
        if amount is not None:
            totals["cost"]["amount"] = totals["cost"].get("amount", 0) + amount
        currency = cost.get("currency")
        if isinstance(currency, str) and currency:
            totals["cost"]["currency"] = currency


def usage_totals_from_diagnostics(
    diagnostics: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Restore accumulated totals from a prior run's diagnostics.

    Used when a run resumes after a HITL interruption so earlier attempts are
    not lost. Falls back to the legacy last-attempt ``usage`` block for runs
    persisted before this accumulation existed.
    """
    totals = new_usage_totals()
    if not isinstance(diagnostics, dict):
        return totals
    prior = diagnostics.get("usage_cumulative")
    if not isinstance(prior, dict):
        accumulate_usage(totals, diagnostics.get("usage"))
        return totals
    for key in _ADDITIVE_KEYS:
        value = _number(prior.get(key))
        if value is not None and value >= 0:
            totals[key] = int(value)
    for key in _MAX_KEYS:
        value = _number(prior.get(f"{key}_max"))
        if value is not None and value >= 0:
            totals[f"{key}_max"] = int(value)
    cost = prior.get("cost")
    if isinstance(cost, dict):
        amount = _number(cost.get("amount"))
        if amount is not None:
            totals["cost"]["amount"] = amount
        currency = cost.get("currency")
        if isinstance(currency, str) and currency:
            totals["cost"]["currency"] = currency
    return totals


def attach_usage_cumulative(
    diagnostics: Dict[str, Any], totals: Dict[str, Any], attempt_count: int
) -> None:
    """Write the accumulated block and attempt count onto ``diagnostics``.

    Only attaches when at least one attempt contributed usage, so runs without
    usage stay free of an all-zero block that the UI would have to special
    case.
    """
    has_any = (
        any(totals.get(key, 0) for key in _ADDITIVE_KEYS)
        or any(totals.get(f"{key}_max", 0) for key in _MAX_KEYS)
        or bool(totals["cost"].get("amount") or totals["cost"].get("currency"))
    )
    if not has_any:
        return
    payload: Dict[str, Any] = {
        "input": totals["input"],
        "output": totals["output"],
        "total": totals["total"],
        "cached": totals["cached"],
    }
    # Omit zeroed context/cost values so the UI never renders "使用 0 / 0" or
    # "費用 0" for providers that do not report them.
    if totals["used_max"] > 0:
        payload["used_max"] = totals["used_max"]
    if totals["size_max"] > 0:
        payload["size_max"] = totals["size_max"]
    cost = totals["cost"]
    if cost.get("amount") or cost.get("currency"):
        payload["cost"] = dict(cost)
    diagnostics["usage_cumulative"] = payload
    diagnostics["worker_attempt_count"] = attempt_count
