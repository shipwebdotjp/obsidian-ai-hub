"""Context aggregation for AI planner proposal generation.

The planner may only propose items the person explicitly wrote down, so the
context is deliberately narrow:

- citable evidence lines from the last few daily notes (the only allowed
  source of a proposal),
- long-term memory (background only, never citable),
- the authoritative upcoming schedule (duplicate avoidance),
- pending Inbox approvals and past proposals (rendered separately).

Activity logs, day/week summaries, research themes and active projects are
excluded on purpose: inferring "what to do next" from work records is the
noise this design removes. Each block degrades gracefully to an empty string
when its source fails.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from obsidian_ai_hub.planner import apple, notes, recurring

logger = logging.getLogger(__name__)

MAX_BLOCK_ITEMS = 30
MAX_REJECTION_COMMENT_CHARS = 120
SCHEDULE_CONTEXT_DAYS = 30


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = (text or "").replace("\r", " ").replace("\n", " ").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _build_evidence_block(evidence_lines: list[notes.EvidenceLine]) -> str:
    if not evidence_lines:
        return ""
    lines = [
        "## ユーザーが自分で書いた用件（候補の根拠にできる唯一の材料）",
        "evidence.ref には各行頭の [E番号] をそのまま使う。",
    ]
    current_day: date | None = None
    for line in evidence_lines:
        if line.date != current_day:
            current_day = line.date
            lines.append(f"### {current_day.isoformat()}")
        lines.append(f"[{line.ref}] {line.text}")
    return "\n".join(lines)


def _build_memory_block() -> str:
    from obsidian_ai_hub.memory import context as memory_context

    try:
        compiled = memory_context.compile_context("planner")
    except Exception:
        logger.exception("Failed to compile long-term memory context")
        return ""
    text = (compiled or {}).get("context", "")
    if not text or not text.strip():
        return ""
    return (
        "## 長期メモリ（背景情報。候補の根拠には使わない）\n" + text.strip()
    )


def _build_authoritative_schedule_block(
    reference_date: date | None = None,
) -> str:
    """Format upcoming Apple and configured recurring items for the LLM.

    Apple Calendar and Reminders are fetched live through the planner's
    short-lived cache. Configured recurring items are expanded from their
    read-only source of truth. Neither source is persisted as part of proposal
    generation.
    """
    start_date = reference_date or date.today()
    end_date = start_date + timedelta(days=SCHEDULE_CONTEXT_DAYS - 1)

    try:
        external = apple.get_external_data(start_date, end_date) or {}
    except Exception:
        logger.exception("Failed to load Apple schedule for planner context")
        external = {}

    try:
        recurring_items = recurring.expand_recurring(start_date, end_date)
    except Exception:
        logger.exception("Failed to expand recurring schedule for planner context")
        recurring_items = []

    apple_events = external.get("calendar_events", []) or []
    apple_reminders = external.get("reminders", []) or []
    if not apple_events and not apple_reminders and not recurring_items:
        return ""

    lines = [
        "## 今後30日間の正本スケジュール"
        f"（{start_date.isoformat()}〜{end_date.isoformat()}）"
    ]

    if apple_events:
        lines.append("### Apple Calendar")
        for event in apple_events[:MAX_BLOCK_ITEMS]:
            title = _truncate_text(str(event.get("title") or ""), 200)
            if not title:
                continue
            start = event.get("start") or "日時未設定"
            end = event.get("end") or ""
            timing = str(start) if not end else f"{start}〜{end}"
            all_day = " / 終日" if event.get("all_day") else ""
            lines.append(f"- {timing}{all_day} | {title}")

    if apple_reminders:
        lines.append("### Apple Reminders")
        for reminder in apple_reminders[:MAX_BLOCK_ITEMS]:
            title = _truncate_text(str(reminder.get("title") or ""), 200)
            if not title:
                continue
            due = reminder.get("due") or "期限未設定"
            lines.append(f"- {due} | {title}")

    if recurring_items:
        lines.append("### CONFIG 定期予定")
        for item in recurring_items[:MAX_BLOCK_ITEMS]:
            title = _truncate_text(str(item.get("title") or ""), 200)
            if not title:
                continue
            item_date = item.get("date")
            day = item_date.isoformat() if isinstance(item_date, date) else str(item_date)
            kind = "タスク" if item.get("kind") == "task" else "予定"
            if not item.get("all_day") and item.get("start_time"):
                try:
                    from datetime import datetime

                    start_hm = datetime.fromisoformat(str(item["start_time"])).strftime("%H:%M")
                    end_hm = ""
                    if item.get("end_time"):
                        end_hm = datetime.fromisoformat(str(item["end_time"])).strftime("%H:%M")
                    timing = f"{start_hm}~{end_hm}" if end_hm else start_hm
                    lines.append(f"- {day} {timing} / {kind} | {title}")
                    continue
                except ValueError:
                    pass
            lines.append(f"- {day} / {kind} | {title}")

    return "\n".join(lines)


def build_planner_context_pack(
    evidence_lines: list[notes.EvidenceLine] | None = None,
) -> str:
    """Render the LLM context pack.

    Callers that already collected evidence lines pass them in so the same
    IDs are used for validation.
    """
    if evidence_lines is None:
        evidence_lines = notes.collect_citable_lines()
    blocks = [
        _build_evidence_block(evidence_lines),
        _build_memory_block(),
        _build_authoritative_schedule_block(),
    ]
    return "\n\n".join(b for b in blocks if b)


def build_excluded_inbox_items() -> str:
    """List Inbox calendar/reminder items already pending human approval.

    The planner generator must not propose duplicates of items that are already
    awaiting approval through the existing Inbox -> HITL flow.
    """
    from obsidian_ai_hub.hitl import store as hitl_store

    try:
        runs, _ = hitl_store.list_runs(status="pending_user", limit=50)
    except Exception:
        logger.exception("Failed to load pending HITL runs")
        return "(none)"

    lines: list[str] = []
    for run in runs:
        handler = run.get("handler") or ""
        if handler not in ("calendar.add_approved_event", "reminders.add_approved_reminder"):
            continue
        title = run.get("title") or ""
        if title:
            lines.append(f"- [{handler}] {title}")

    if not lines:
        return "(none)"
    return "\n".join(lines)


def build_existing_proposals_block() -> str:
    """Summarize recent proposed/promoted/rejected proposals to avoid re-proposing them.

    `proposed` (pending, neither approved nor rejected) is included so the LLM
    does not waste slots re-generating items the user is still deliberating on.
    """
    from obsidian_ai_hub.planner import feedback, store

    lines: list[str] = []
    for status in ("proposed", "promoted", "rejected"):
        try:
            proposals = store.list_proposals(status=status, limit=15)
        except Exception:
            logger.exception("Failed to load %s proposals", status)
            continue
        for p in proposals:
            title = p.get("title") or ""
            if not title:
                continue
            anchor = p.get("start_time") or p.get("due_date") or ""
            label = status
            if status == "rejected":
                reason = p.get("rejection_reason")
                if reason:
                    label = f"rejected/{reason} {feedback.rejection_reason_label(reason)}"
            line = f"- [{label}] {title} ({p.get('kind')} {anchor})".strip()
            if status == "rejected" and p.get("rejection_comment"):
                comment = str(p["rejection_comment"]).strip()
                if comment:
                    line += f" — コメント: {comment[:MAX_REJECTION_COMMENT_CHARS]}"
            lines.append(line)

    if not lines:
        return "(none)"
    return "\n".join(lines[:MAX_BLOCK_ITEMS])
