"""Shared helpers for Coding ask_user HITL interruption and resume."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def load_prior_history_sync(prior_hitl_run_id: Optional[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Load carried history and resume state from a prior HITL checkpoint (sync).

    Returns (qa_history, resume_state). Empty on missing/invalid checkpoints;
    callers log the cause. Never raises for malformed prior state so a
    corrupted audit trail does not block a new interruption.
    """
    if not prior_hitl_run_id:
        return [], {}
    try:
        from obsidian_ai_hub.hitl import store as hitl_store

        prior_hitl = hitl_store.get_run(prior_hitl_run_id)
        if not prior_hitl or not prior_hitl.get("checkpoint"):
            return [], {}
        prior_cp = json.loads(prior_hitl["checkpoint"])
        if not isinstance(prior_cp, dict):
            return [], {}
        from obsidian_ai_hub.agents.ask_user import carry_history_for_new_checkpoint

        hist = carry_history_for_new_checkpoint(prior_cp)
        rs = prior_cp.get("resume_state")
        return hist, rs if isinstance(rs, dict) else {}
    except Exception as exc:
        logger.warning("Failed to carry HITL history from %s: %s", prior_hitl_run_id, exc)
        return [], {}


def build_coding_checkpoint(
    *,
    session_id: str,
    run_id: str,
    user_prompt: str,
    repo_path: str,
    backend_name: str,
    ask_call: Dict[str, Any],
    questions_data: List[Dict[str, Any]],
    phase: str,
    phase_turn: int,
    cli_count: int,
    tool_ids: List[str],
    provider: str,
    model: str,
    prior_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a v2 Coding ask_user checkpoint with carried history."""
    return {
        "domain": "coding",
        "session_id": session_id,
        "run_id": run_id,
        "user_prompt": user_prompt,
        "repo_path": repo_path,
        "backend_name": backend_name,
        "tool_call_id": ask_call.get("id") or f"call_{phase_turn}_ask_user",
        "ask_user_args": ask_call.get("args", {}),
        "questions": questions_data,
        "qa_history": list(prior_history) if prior_history else [],
        "resume_state": {
            "cli_count": cli_count,
            "phase": phase,
            "phase_turn": phase_turn,
        },
        "phase": phase,
        "phase_turn": phase_turn,
        "cli_count": cli_count,
        "tool_ids": tool_ids,
        "provider": provider,
        "model": model,
    }


def restore_coding_progress(prior_hitl_run_id: Optional[str]) -> Tuple[int, int]:
    """Restore (cli_count, phase_turn) from a prior checkpoint (sync).

    Returns (0, 0) when no resumable state exists.
    """
    _, rs = load_prior_history_sync(prior_hitl_run_id)
    try:
        cli_count = int(rs.get("cli_count") or 0)
    except (TypeError, ValueError):
        cli_count = 0
    try:
        phase_turn = int(rs.get("phase_turn") or 0)
    except (TypeError, ValueError):
        phase_turn = 0
    return max(cli_count, 0), max(phase_turn, 0)
