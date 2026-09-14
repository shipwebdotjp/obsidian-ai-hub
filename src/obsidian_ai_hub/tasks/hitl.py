"""HITL resume handler for Task target-resolution questions.

Registered in the composition root (``main.register_hitl_handlers``).
Any answer re-queues the task for replanning.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_task_target(ctx: Any) -> Any:
    """Re-queue the task after its target question is answered."""
    from obsidian_ai_hub.hitl.dispatcher import HitlResult
    from obsidian_ai_hub.tasks import store as task_store

    try:
        checkpoint = json.loads(ctx.checkpoint or "{}")
    except (json.JSONDecodeError, TypeError):
        checkpoint = {}
    task_id = checkpoint.get("task_id")
    if not task_id:
        logger.warning("Task resolve handler got checkpoint without task_id")
        return HitlResult.complete()
    answer = ctx.answers_by_question_key.get("target")
    task_store.transition_task_status(str(task_id), "queued", conn=ctx.conn)
    task_store.append_task_event(
        str(task_id),
        "hitl_question_answered",
        {"hitl_run_id": ctx.run_id, "answer": answer},
        conn=ctx.conn,
    )
    return HitlResult.complete()
