"""HITL resume handlers for agents.ask_user and coding.ask_user."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Dict, Optional

from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.coding import store as coding_store
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl.dispatcher import HitlContext, HitlResult

logger = logging.getLogger(__name__)


def _format_answers(raw_answers: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize raw answers by question key into selection/text payloads."""
    formatted: Dict[str, Any] = {}
    for q_key, ans in (raw_answers or {}).items():
        if isinstance(ans, dict):
            val = ans.get("value")
            comment = ans.get("comment")
        else:
            val = ans
            comment = None

        if val == "other":
            formatted[q_key] = {
                "selection": "other",
                "text": comment or None,
            }
        else:
            formatted[q_key] = {
                "selection": val,
                "text": None,
            }
    return formatted


def _load_checkpoint(ctx: HitlContext, label: str) -> Dict[str, Any]:
    raw_cp = ctx.checkpoint
    if not raw_cp:
        raise ValueError(f"{label} ask_user HITL run missing checkpoint.")

    try:
        cp = json.loads(raw_cp)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {label} ask_user checkpoint JSON.") from exc
    if not isinstance(cp, dict):
        raise ValueError(f"Invalid {label} ask_user checkpoint JSON.")
    return cp


def _clear_coding_hitl_link(run_id: str) -> None:
    """Clear coding_runs.hitl_run_id (update_run() cannot clear it with None)."""
    conn = get_db_connection()
    try:
        try:
            conn.execute(
                "UPDATE coding_runs SET hitl_run_id = NULL WHERE run_id = ?",
                (run_id,),
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "no such column: hitl_run_id" not in str(exc):
                raise
            logger.warning(
                "coding_runs.hitl_run_id missing; run %s link not cleared. Run migration v33.",
                run_id,
            )
    finally:
        conn.close()


def handle_agent_ask_user(ctx: HitlContext) -> HitlResult:
    """HITL handler to resume an Agent run after user answers ask_user questions."""
    cp = _load_checkpoint(ctx, "Agent")

    run_id = cp.get("run_id")
    tool_call_id = cp.get("tool_call_id")
    if not run_id or not tool_call_id:
        raise ValueError("Checkpoint missing run_id or tool_call_id.")

    formatted_answers = _format_answers(ctx.raw_answers_by_question_key)

    # Resume Agent run by transitioning from waiting_user back to succeeded
    agent_store.update_run_hitl(run_id=run_id, status="succeeded", hitl_run_id=None)

    merged = dict(cp)
    merged["answers"] = formatted_answers
    return HitlResult.complete(checkpoint=json.dumps(merged, ensure_ascii=False))


def handle_coding_ask_user(ctx: HitlContext) -> HitlResult:
    """HITL handler to resume a Coding Orchestrator run after user answers ask_user questions."""
    cp = _load_checkpoint(ctx, "Coding")

    run_id = cp.get("run_id")
    if not run_id:
        raise ValueError("Checkpoint missing run_id.")

    formatted_answers = _format_answers(ctx.raw_answers_by_question_key)

    # Update coding run status back from waiting_user to completed
    coding_store.update_run(run_id=run_id, status="completed")
    _clear_coding_hitl_link(run_id)

    merged = dict(cp)
    merged["answers"] = formatted_answers
    return HitlResult.complete(checkpoint=json.dumps(merged, ensure_ascii=False))
