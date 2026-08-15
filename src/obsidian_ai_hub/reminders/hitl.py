from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from obsidian_ai_hub.hitl.dispatcher import HitlContext, HitlResult
from obsidian_ai_hub.hitl.service import register_run_and_questions

logger = logging.getLogger(__name__)

HANDLER_NAME = "reminders.add_approved_reminder"
DISPLAY_TYPE = "リマインダー登録"


def _build_run_id(content: str, due_date: str | None = None) -> str:
    identity = f"{content}\x00{due_date or ''}"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"hrun_inbox_reminder_{digest}"


def _format_reminder_line(reminder: dict) -> str:
    title = reminder.get("title") or "(タイトルなし)"
    due_date = reminder.get("due_date")
    parts = [f"「{title}」"]
    if due_date:
        parts.append(f"期限: {due_date}")
    return " / ".join(parts)


def register_reminder_approval(
    content: str,
    reminder: dict,
) -> Optional[str]:
    """
    Register a HITL run asking the user to approve adding a reminder.

    Deterministic run_id (content + due_date hash) keeps the registration
    idempotent so a repeated inbox merge of the same reminder never creates
    duplicate approval runs, while distinct reminders sharing the same raw text
    still get separate runs. Returns the run_id, or None if registration fails.
    """
    due_date = reminder.get("due_date")
    run_id = _build_run_id(content, due_date)
    title = str(reminder.get("title") or "").strip() or content.strip()[:40]
    reminder_line = _format_reminder_line(reminder)
    description = (
        f"{reminder_line}\n\n元の内容:\n{content.strip()}"
        if content.strip()
        else reminder_line
    )

    # A completed run must not be re-registered: re-registration would reset
    # the checkpoint to awaiting_approval and the status to ready_to_resume
    # while preserving the already-submitted approve answer, so the next
    # dispatch would re-add the reminder without a fresh approval.
    from obsidian_ai_hub.hitl.store import get_run

    existing = get_run(run_id)
    if existing and existing.get("status") == "completed":
        logger.info(
            "Reminder approval run %s already completed; skipping re-registration",
            run_id,
        )
        return run_id

    questions_data = [
        {
            "question_key": "action",
            "question_type": "select",
            "display_text": f"この内容をリマインダーに登録しますか？\n{reminder_line}",
            "title": "リマインダー登録",
            "prompt": "この内容をリマインダーに登録しますか？",
            "choices": [
                {
                    "value": "approve",
                    "label": "承認",
                    "description": "リマインダーに登録します。",
                },
                {
                    "value": "decline",
                    "label": "登録しない",
                    "description": "リマインダーには登録しません。",
                },
            ],
            "is_required": 1,
            "context_json": {
                "type": "reminder",
                "reminder": {
                    "title": reminder.get("title"),
                    "due_date": reminder.get("due_date"),
                },
                "content": content,
            },
        }
    ]

    checkpoint = json.dumps(
        {
            "type": "reminder",
            "reminder": {
                "title": reminder.get("title"),
                "due_date": reminder.get("due_date"),
            },
            "content": content,
            "phase": "awaiting_approval",
        }
    )

    try:
        register_run_and_questions(
            run_id=run_id,
            handler=HANDLER_NAME,
            checkpoint=checkpoint,
            question_set_id="confirm_reminder",
            questions_data=questions_data,
            display_type=DISPLAY_TYPE,
            title=title,
            description=description,
        )
    except Exception:
        logger.exception("Failed to register reminder approval HITL run")
        return None

    # Notify via LINE as a best-effort push after commit; a notification
    # failure must never fail the registration.
    try:
        from obsidian_ai_hub.line_notification import notify_hitl_run

        notify_hitl_run(
            kind=DISPLAY_TYPE,
            title=title,
            description=description,
            run_id=run_id,
        )
    except Exception as exc:
        logger.warning(
            "LINE reminder notification failed after commit for run %s: %s",
            run_id,
            type(exc).__name__,
        )
    return run_id


def add_approved_reminder(ctx: HitlContext) -> HitlResult:
    """
    HITL handler executed after a reminder approval run is answered.

    On approval, adds the reminder to the macOS Reminders via the existing
    add_reminder tool. The checkpoint phase guards against re-adding the
    reminder on a re-dispatch after a partial failure.
    """
    checkpoint = {}
    if ctx.checkpoint:
        try:
            checkpoint = json.loads(ctx.checkpoint)
        except (TypeError, ValueError):
            checkpoint = {}

    answer = ctx.answers_by_question_key.get("action")
    if not answer:
        return HitlResult.fail(
            "Action answer not found in active question set answers."
        )
    if isinstance(answer, dict):
        answer = answer.get("value", answer)

    if answer not in ("approve", "decline"):
        return HitlResult.fail(f"Unexpected action answer: {answer!r}")

    if answer != "approve":
        logger.info("Reminder approval run %s declined", ctx.run_id)
        return HitlResult.complete(
            checkpoint=json.dumps({**checkpoint, "phase": "declined"})
        )

    if checkpoint.get("phase") == "added":
        logger.info("Reminder for run %s already added; skipping", ctx.run_id)
        return HitlResult.complete(checkpoint=ctx.checkpoint)

    reminder = checkpoint.get("reminder") or {}
    title = reminder.get("title")
    if not title:
        return HitlResult.fail("Missing title in reminder checkpoint")

    from obsidian_ai_hub.handler.apple_reminders import add_reminder

    kwargs = {
        "title": title,
        "due_date": reminder.get("due_date"),
    }
    try:
        result = add_reminder.invoke(kwargs)
    except Exception as exc:
        logger.exception("add_reminder raised for run %s", ctx.run_id)
        return HitlResult.fail(f"Failed to add reminder: {type(exc).__name__}: {exc}")
    logger.info("add_reminder result for run %s: %s", ctx.run_id, result)

    if not isinstance(result, str) or not result.startswith("Successfully"):
        return HitlResult.fail(f"Failed to add reminder: {result}")

    # Return the phase='added' checkpoint to the dispatcher, which persists it
    # atomically with the run status in a single transaction.
    return HitlResult.complete(checkpoint=json.dumps({**checkpoint, "phase": "added"}))
