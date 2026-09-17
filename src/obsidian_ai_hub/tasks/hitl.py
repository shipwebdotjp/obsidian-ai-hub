"""HITL resume handler for Task target-resolution questions.

Registered in the composition root (``main.register_hitl_handlers``).
A valid answer is persisted as a ``target_resolution_selected`` event
(human selections carry no confidence) and the task re-queues for
replanning with the selection as forced input.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_task_target(ctx: Any) -> Any:
    """Re-queue the task after its target question is answered."""
    from obsidian_ai_hub.hitl.dispatcher import HitlResult
    from obsidian_ai_hub.tasks import planning, store as task_store

    try:
        checkpoint = json.loads(ctx.checkpoint or "{}")
    except (json.JSONDecodeError, TypeError):
        checkpoint = {}
    task_id = checkpoint.get("task_id")
    if not task_id:
        logger.warning("Task resolve handler got checkpoint without task_id")
        return HitlResult.complete()
    answer = ctx.answers_by_question_key.get("target")
    comment = _extract_answer_comment(ctx)
    selection = planning.parse_selection_value(answer)
    if selection is not None:
        try:
            planning.record_target_resolution_selection(
                str(task_id),
                kind=selection["kind"],
                project_id=selection["project_id"],
                via="hitl",
                conn=ctx.conn,
            )
        except ValueError as exc:
            # The selected project vanished (or is invalid) while the human
            # answered. Re-ask with the live option set instead of stranding
            # the task on a rejected selection.
            logger.warning(
                "Task %s target answer rejected (%s); re-asking", task_id, exc
            )
            _register_retry_questions(ctx, str(task_id), str(exc))
            return HitlResult.re_suspend()
    task_store.transition_task_status(str(task_id), "queued", conn=ctx.conn)
    task_store.append_task_event(
        str(task_id),
        "hitl_question_answered",
        {"hitl_run_id": ctx.run_id, "answer": answer, "comment": comment},
        conn=ctx.conn,
    )
    return HitlResult.complete()


def _register_retry_questions(ctx: Any, task_id: str, reason: str) -> None:
    """Re-register the target question with the live valid-project options."""
    from obsidian_ai_hub.tasks import planning

    projects = planning.list_valid_projects()
    options: list[dict[str, str]] = []
    for project in projects:
        try:
            project_id = int(project.get("project_id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if project_id <= 0:
            continue
        name = str(project.get("name") or "")
        options.append(
            {
                "value": f"project:{project_id}",
                "label": f"{name}（Project {project_id}）" if name else f"Project {project_id}",
            }
        )
    options.append({"value": "general", "label": "一般Task（Projectを特定しない）"})
    ctx.register_next_questions(
        question_set_id="target_retry",
        questions_data=[
            {
                "question_key": "target",
                "question_type": "select",
                "display_text": (
                    "選択された対象は利用できなくなりました"
                    f"（{reason}）。改めて対象のProject、"
                    "または一般Taskを選んでください。"
                ),
                "title": "Taskの対象確認",
                "prompt": "対象のProject、または一般Taskを選んでください。",
                "choices": options,
                "is_required": 1,
            }
        ],
        checkpoint=json.dumps({"task_id": task_id}, ensure_ascii=False),
    )


def _extract_answer_comment(ctx: Any) -> str | None:
    """Return the free-text comment attached to the target answer, if any."""
    raw_answers = getattr(ctx, "raw_answers_by_question_key", None)
    if not isinstance(raw_answers, dict):
        return None
    raw = raw_answers.get("target")
    if isinstance(raw, dict):
        comment = raw.get("comment")
    else:
        return None
    if isinstance(comment, str) and comment.strip():
        return comment.strip()
    return None
