"""HITL resume handler for ``workflow.hitl_wait`` capability nodes.

Registered in the composition root (``main.register_hitl_handlers``). The
answer is stored as a ``hitl_answer_received`` workflow event keyed by
``activation_id`` and the run is requeued; the engine resumes the same
activation and marks the node succeeded.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_workflow_hitl(ctx: Any) -> Any:
    """Store the human answer and requeue the workflow run."""
    from obsidian_ai_hub.hitl.dispatcher import HitlResult
    from obsidian_ai_hub.workflow import store as workflow_store

    try:
        checkpoint = json.loads(ctx.checkpoint or "{}")
    except (json.JSONDecodeError, TypeError):
        checkpoint = {}
    run_id = checkpoint.get("run_id")
    activation_id = checkpoint.get("activation_id")
    node_id = checkpoint.get("node_id")
    if not run_id or not activation_id:
        logger.warning("Workflow HITL handler got checkpoint without run/activation")
        return HitlResult.complete()
    answers = getattr(ctx, "answers_by_question_key", {}) or {}
    answer = answers.get("workflow_answer")
    workflow_store.append_event(
        str(run_id),
        "hitl_answer_received",
        {
            "node_id": node_id,
            "activation_id": activation_id,
            "hitl_run_id": ctx.run_id,
            "answer": answer,
        },
        conn=ctx.conn,
    )
    run = workflow_store.get_run(str(run_id), conn=ctx.conn)
    if run is not None and str(run["status"]) == "waiting_hitl":
        workflow_store.transition_run_status(
            str(run_id), "queued", conn=ctx.conn
        )
    return HitlResult.complete()
