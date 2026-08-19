"""Planner web service functions.

Composes the Planner screen's four layers: Apple events/reminders (external,
never persisted), recurring config expansion (config is the source of truth),
Inbox calendar/reminder items still awaiting human approval (existing HITL
flow), and AI proposals (planner_proposals). Also exposes proposal CRUD,
reject, promote, and on-demand generation.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Optional

from obsidian_ai_hub.hitl import store as hitl_store
from obsidian_ai_hub.planner import apple, promote as promote_service, recurring, store, suggest

logger = logging.getLogger(__name__)

CALENDAR_HANDLER = "calendar.add_approved_event"
REMINDER_HANDLER = "reminders.add_approved_reminder"


def _parse_checkpoint(run: dict) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Extract (start_time, end_time, location, due_date) from a HITL checkpoint."""
    checkpoint_raw = run.get("checkpoint")
    if not checkpoint_raw:
        return None, None, None, None
    try:
        checkpoint = json.loads(checkpoint_raw)
    except (TypeError, ValueError):
        return None, None, None, None

    if checkpoint.get("type") == "calendar_event":
        event = checkpoint.get("event") or {}
        return (
            event.get("start_time"),
            event.get("end_time"),
            event.get("location"),
            None,
        )
    if checkpoint.get("type") == "reminder":
        reminder = checkpoint.get("reminder") or {}
        return None, None, None, reminder.get("due_date")
    return None, None, None, None


def _list_pending_inbox() -> list[dict]:
    try:
        runs, _ = hitl_store.list_runs(status="pending_user", limit=100)
    except Exception:
        logger.exception("Failed to list pending HITL runs for planner")
        return []

    items: list[dict] = []
    for run in runs:
        handler = run.get("handler") or ""
        if handler not in (CALENDAR_HANDLER, REMINDER_HANDLER):
            continue
        title = run.get("title") or ""
        if not title:
            continue
        start_time, end_time, location, due_date = _parse_checkpoint(run)
        items.append(
            {
                "run_id": run["run_id"],
                "handler": handler,
                "title": title,
                "kind": "calendar" if handler == CALENDAR_HANDLER else "reminder",
                "start_time": start_time,
                "end_time": end_time,
                "location": location,
                "due_date": due_date,
            }
        )
    return items


def get_planner_timeline(start_date: date, end_date: date) -> dict:
    external = apple.get_external_data(start_date, end_date)

    apple_events = []
    for ev in external.get("calendar_events", []) or []:
        if ev.get("all_day"):
            apple_events.append(
                {
                    "title": ev.get("title") or "",
                    "start_time": None,
                    "end_time": None,
                    "location": None,
                    "all_day": True,
                }
            )
        else:
            apple_events.append(
                {
                    "title": ev.get("title") or "",
                    "start_time": ev.get("start"),
                    "end_time": ev.get("end"),
                    "location": None,
                    "all_day": False,
                }
            )

    apple_reminders = [
        {"title": r.get("title") or "", "due_date": r.get("due")}
        for r in (external.get("reminders", []) or [])
    ]

    recurring_items = recurring.expand_recurring(start_date, end_date)

    return {
        "apple_events": apple_events,
        "apple_reminders": apple_reminders,
        "apple_error": external.get("error"),
        "recurring_events": [
            {
                "title": item["title"],
                "date": item["date"].isoformat(),
                "category": item["category"],
            }
            for item in recurring_items
        ],
        "inbox_pending": _list_pending_inbox(),
        "ai_proposals": store.list_proposals(status="proposed"),
    }


def list_planner_proposals(
    *,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    items = store.list_proposals(status=status, kind=kind)
    total = len(items)
    return items[offset : offset + limit], total


def get_planner_proposal(proposal_id: str) -> Optional[dict]:
    return store.get_proposal(proposal_id)


def update_planner_proposal(proposal_id: str, payload: dict) -> dict:
    return store.update_proposal_fields(
        proposal_id,
        kind=payload.get("kind"),
        title=payload.get("title"),
        start_time=validate_iso_datetime(payload.get("start_time")),
        end_time=validate_iso_datetime(payload.get("end_time")),
        location=payload.get("location"),
        due_date=validate_iso_datetime(payload.get("due_date")),
        rationale=payload.get("rationale"),
    )


def reject_planner_proposal(proposal_id: str, reason: Optional[str] = None) -> dict:
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise LookupError(f"Proposal not found: {proposal_id}")
    changed = store.transition_status(
        proposal_id, to_status="rejected", external_result=reason
    )
    if not changed:
        raise ValueError(f"Proposal {proposal_id} is not 'proposed'")
    updated = store.get_proposal(proposal_id)
    if updated is None:
        raise RuntimeError(f"Proposal {proposal_id} vanished after rejection")
    return updated


def promote_planner_proposal(proposal_id: str) -> dict:
    return promote_service.promote_proposal(proposal_id)


def generate_planner_proposals() -> list[dict]:
    return suggest.generate_proposals(source="manual")


def validate_iso_datetime(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    try:
        datetime.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"Invalid ISO datetime: {value}")
    return value.strip()