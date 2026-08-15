from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from obsidian_ai_hub.hitl.dispatcher import HitlContext, HitlResult
from obsidian_ai_hub.hitl.service import register_run_and_questions
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

HANDLER_NAME = "calendar.add_approved_event"
DISPLAY_TYPE = "カレンダー登録"


def _build_run_id(content: str, start_time: str | None = None) -> str:
    identity = f"{content}\x00{start_time or ''}"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"hrun_inbox_calendar_{digest}"


def _format_event_line(event: dict) -> str:
    title = event.get("title") or "(タイトルなし)"
    start_time = event.get("start_time")
    end_time = event.get("end_time")
    location = event.get("location")

    parts = [f"「{title}」"]
    if start_time:
        parts.append(f"{start_time}")
    if end_time:
        parts.append(f"〜 {end_time}")
    if location:
        parts.append(f"場所: {location}")
    return " / ".join(parts)


def register_calendar_event_approval(
    content: str,
    event: dict,
) -> Optional[str]:
    """
    Register a HITL run asking the user to approve adding a calendar event.

    Deterministic run_id (content + start_time hash) keeps the registration
    idempotent so a repeated inbox merge of the same event never creates
    duplicate approval runs, while distinct events sharing the same raw text
    still get separate runs. Returns the run_id, or None if registration fails.
    """
    start_time = event.get("start_time")
    run_id = _build_run_id(content, start_time)
    title = str(event.get("title") or "").strip() or content.strip()[:40]
    event_line = _format_event_line(event)
    description = (
        f"{event_line}\n\n元の内容:\n{content.strip()}"
        if content.strip()
        else event_line
    )

    # A completed run must not be re-registered: re-registration would reset
    # the checkpoint to awaiting_approval and the status to ready_to_resume
    # while preserving the already-submitted approve answer, so the next
    # dispatch would re-add the event without a fresh approval.
    from obsidian_ai_hub.hitl.store import get_run

    existing = get_run(run_id)
    if existing and existing.get("status") == "completed":
        logger.info(
            "Calendar approval run %s already completed; skipping re-registration",
            run_id,
        )
        return run_id

    questions_data = [
        {
            "question_key": "action",
            "question_type": "select",
            "display_text": f"この内容をカレンダーに登録しますか？\n{event_line}",
            "title": "カレンダー登録",
            "prompt": "この内容をカレンダーに登録しますか？",
            "choices": [
                {
                    "value": "approve",
                    "label": "承認",
                    "description": "カレンダーに登録します。",
                },
                {
                    "value": "decline",
                    "label": "登録しない",
                    "description": "カレンダーには登録しません。",
                },
            ],
            "is_required": 1,
            "context_json": {
                "type": "calendar_event",
                "event": {
                    "title": event.get("title"),
                    "start_time": event.get("start_time"),
                    "end_time": event.get("end_time"),
                    "location": event.get("location"),
                },
                "content": content,
            },
        }
    ]

    checkpoint = json.dumps(
        {
            "type": "calendar_event",
            "event": {
                "title": event.get("title"),
                "start_time": event.get("start_time"),
                "end_time": event.get("end_time"),
                "location": event.get("location"),
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
            question_set_id="confirm_calendar",
            questions_data=questions_data,
            display_type=DISPLAY_TYPE,
            title=title,
            description=description,
        )
    except Exception:
        logger.exception("Failed to register calendar approval HITL run")
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
            "LINE calendar notification failed after commit for run %s: %s",
            run_id,
            type(exc).__name__,
        )
    return run_id


def add_approved_calendar_event(ctx: HitlContext) -> HitlResult:
    """
    HITL handler executed after a calendar approval run is answered.

    On approval, adds the event to the macOS Calendar via the existing
    add_calendar_event tool. The checkpoint phase guards against re-adding the
    event on a re-dispatch after a partial failure.
    """
    checkpoint = {}
    if ctx.checkpoint:
        try:
            checkpoint = json.loads(ctx.checkpoint)
        except (TypeError, ValueError):
            checkpoint = {}

    answer = ctx.answers_by_question_key.get("action")
    if not answer:
        return HitlResult.fail("Action answer not found in active question set answers.")
    if isinstance(answer, dict):
        answer = answer.get("value", answer)

    if answer not in ("approve", "decline"):
        return HitlResult.fail(f"Unexpected action answer: {answer!r}")

    if answer != "approve":
        logger.info("Calendar approval run %s declined", ctx.run_id)
        return HitlResult.complete(
            checkpoint=json.dumps({**checkpoint, "phase": "declined"})
        )

    if checkpoint.get("phase") == "added":
        logger.info("Calendar event for run %s already added; skipping", ctx.run_id)
        return HitlResult.complete(checkpoint=ctx.checkpoint)

    event = checkpoint.get("event") or {}
    title = event.get("title")
    start_time = event.get("start_time")
    if not title or not start_time:
        return HitlResult.fail(
            "Missing title or start_time in calendar event checkpoint"
        )

    from obsidian_ai_hub.handler.add_calendar_event import add_calendar_event

    kwargs: dict[str, Any] = {
        "title": title,
        "start_time": start_time,
        "end_time": event.get("end_time"),
        "location": event.get("location"),
        "calendar_name": config.APPLE_CALENDAR_NAME or None,
    }
    result = add_calendar_event.invoke(kwargs)
    logger.info("add_calendar_event result for run %s: %s", ctx.run_id, result)

    if not result.startswith("Successfully"):
        return HitlResult.fail(f"Failed to add calendar event: {result}")

    # Return the phase='added' checkpoint to the dispatcher, which persists it
    # atomically with the run status in a single transaction. Persisting it
    # here via update_checkpoint would be a second, non-atomic write that opens
    # a re-add window if it fails after the event was already created.
    return HitlResult.complete(checkpoint=json.dumps({**checkpoint, "phase": "added"}))