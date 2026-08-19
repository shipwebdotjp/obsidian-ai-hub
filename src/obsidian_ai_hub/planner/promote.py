"""Promote a planner proposal to Apple Calendar / Reminders.

Promotion is atomic from the app's perspective: the Apple write must succeed
before the proposal transitions to 'promoted'. A failed write leaves the
proposal 'proposed' so the user can retry or edit it. The short-lived external
cache is invalidated on success so the Planner screen reflects the new item.
"""

from __future__ import annotations

import logging

from obsidian_ai_hub.handler import add_calendar_event as _add_calendar_event
from obsidian_ai_hub.handler import apple_reminders as _apple_reminders
from obsidian_ai_hub.planner import apple, store

logger = logging.getLogger(__name__)

SUCCESS_PREFIX = "Successfully"


def promote_proposal(proposal_id: str) -> dict:
    """Promote a 'proposed' planner proposal to Apple.

    Returns the updated proposal dict. Raises LookupError when the proposal
    does not exist, ValueError when it is not 'proposed', and RuntimeError
    when the Apple write fails (status is left unchanged).
    """
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise LookupError(f"Proposal not found: {proposal_id}")
    if proposal["status"] != "proposed":
        raise ValueError(
            f"Cannot promote proposal {proposal_id}: status is {proposal['status']!r}"
        )

    if proposal["kind"] == "calendar":
        result = _add_calendar_event.add_calendar_event.invoke(
            {
                "title": proposal["title"],
                "start_time": proposal["start_time"],
                "end_time": proposal["end_time"],
                "location": proposal["location"],
            }
        )
    elif proposal["kind"] == "reminder":
        result = _apple_reminders.add_reminder.invoke(
            {"title": proposal["title"], "due_date": proposal["due_date"]}
        )
    else:
        raise ValueError(f"Unsupported proposal kind: {proposal['kind']}")

    result_text = str(result)
    if not result_text.startswith(SUCCESS_PREFIX):
        raise RuntimeError(f"Apple promotion failed: {result_text}")

    changed = store.transition_status(
        proposal_id,
        to_status="promoted",
        external_result=result_text,
    )
    if not changed:
        raise RuntimeError(f"Proposal {proposal_id} is no longer proposed")

    apple.invalidate_cache()
    updated = store.get_proposal(proposal_id)
    if updated is None:
        raise RuntimeError(f"Proposal {proposal_id} vanished after promotion")
    logger.info("Promoted planner proposal %s: %s", proposal_id, proposal["title"])
    return updated