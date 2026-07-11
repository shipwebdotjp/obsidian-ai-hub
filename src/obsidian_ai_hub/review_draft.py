"""Create and notify a weekly review draft stored in a weekly note."""

from __future__ import annotations

import logging
import re
from datetime import date as date_type
from datetime import datetime, timedelta
from pathlib import Path

from obsidian_ai_hub.utils import config, llm_client, prompt, reader
from obsidian_ai_hub.utils.line_messaging import send_line_push

logger = logging.getLogger(__name__)

REVIEW_DRAFT_START_MARKER = "<!-- obsidian-ai-hub:review-draft:start -->"
REVIEW_DRAFT_END_MARKER = "<!-- obsidian-ai-hub:review-draft:end -->"
REVIEW_HEADINGS = (
    "## 今週の達成",
    "## 目標の振り返り",
    "## 気づき・学び",
    "## 改善したいこと",
    "## 来週の一歩",
)
_EMPTY_RESULT_RE = re.compile(r"^[ \t]*result::[ \t]*$", re.MULTILINE)


def _coerce_target_date(target_date: datetime | date_type | str | None) -> datetime:
    if target_date is None:
        return datetime.now()
    if isinstance(target_date, datetime):
        return target_date
    if isinstance(target_date, date_type):
        return datetime.combine(target_date, datetime.min.time())
    if isinstance(target_date, str):
        return datetime.strptime(target_date, "%Y-%m-%d")
    raise TypeError(f"Unsupported target_date type: {type(target_date)!r}")


def get_week_dates(target_date: datetime) -> list[datetime]:
    """Return Monday through Sunday for the week containing ``target_date``."""
    monday = target_date - timedelta(days=target_date.isoweekday() - 1)
    return [monday + timedelta(days=offset) for offset in range(7)]


def _get_saved_draft(content: str, start_at: int) -> str | None:
    start = content.find(REVIEW_DRAFT_START_MARKER, start_at)
    if start == -1:
        return None
    body_start = start + len(REVIEW_DRAFT_START_MARKER)
    end = content.find(REVIEW_DRAFT_END_MARKER, body_start)
    if end == -1:
        logger.warning("Review draft marker has no closing marker; skipping notification")
        return None
    draft = content[body_start:end].strip()
    return draft or None


def _collect_existing_daily_notes(week_dates: list[datetime]) -> str:
    blocks: list[str] = []
    for day in week_dates:
        daily_path = reader.get_daily_note_path(day)
        if not daily_path.exists():
            continue
        try:
            content = daily_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Could not read daily note %s: %s", daily_path, exc)
            continue
        if content:
            blocks.append(f"# {day:%Y-%m-%d} ({day:%a})\n\n{content}")
    return "\n\n---\n\n".join(blocks)


def _clean_generated_draft(response: object) -> str:
    if not isinstance(response, str):
        return ""
    draft = response.strip()
    if draft.startswith("```") and draft.endswith("```"):
        lines = draft.splitlines()
        if len(lines) >= 2:
            draft = "\n".join(lines[1:-1]).strip()
    return draft


def _has_expected_format(draft: str) -> bool:
    positions = [draft.find(heading) for heading in REVIEW_HEADINGS]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def _send_review_draft(draft: str) -> bool:
    if not config.LINE_MESSAGING_TOKEN or not config.LINE_TARGET_ID:
        logger.error("LINE token or target is not configured; review draft was saved but not sent")
        return False
    if send_line_push(config.LINE_MESSAGING_TOKEN, config.LINE_TARGET_ID, draft):
        logger.info("Sent weekly review draft to LINE")
        return True
    logger.error("Failed to send weekly review draft to LINE")
    return False


def review_draft(target_date: datetime | date_type | str | None = None) -> bool:
    """Save a draft when needed, then send the saved draft as a LINE Push message.

    Returns ``True`` only when a draft was successfully sent. Expected no-op and
    failure conditions are logged and return ``False`` so scheduled execution
    does not fail noisily.
    """
    try:
        target_date = _coerce_target_date(target_date)
    except (TypeError, ValueError) as exc:
        logger.error("Invalid review target date: %s", exc)
        return False

    weekly_note = reader.get_weekly_note_content(target_date)
    result_match = _EMPTY_RESULT_RE.search(weekly_note)
    if result_match is None:
        logger.info("Weekly note has no empty result:: field; skipping review draft")
        return False

    saved_draft = _get_saved_draft(weekly_note, result_match.end())
    if saved_draft is not None:
        logger.info("Using saved weekly review draft for LINE retry")
        return _send_review_draft(saved_draft)

    daily_notes = _collect_existing_daily_notes(get_week_dates(target_date))
    if not daily_notes:
        logger.info("No daily notes found for this week; skipping review draft")
        return False

    try:
        rendered_prompt = prompt.render_prompt(
            config.REVIEW_DRAFT_PROMPT_PATH,
            {
                "WEEKLY_NOTE": weekly_note,
                "DAILY_NOTES": daily_notes,
            },
        )
        draft = _clean_generated_draft(
            llm_client.generate_llm_response(
                provider=config.REVIEW_DRAFT_PROVIDER,
                model=config.REVIEW_DRAFT_MODEL,
                prompt=rendered_prompt,
                max_tokens=8192,
            )
        )
    except Exception as exc:
        logger.error("Failed to generate weekly review draft: %s", exc)
        return False

    if not draft:
        logger.warning("LLM returned an empty weekly review draft")
        return False
    if not _has_expected_format(draft):
        logger.warning("LLM response did not use the required weekly review headings")
        return False

    weekly_note_path = reader.get_weekly_note_path(target_date)
    updated_note = (
        weekly_note[:result_match.end()]
        + f"\n{REVIEW_DRAFT_START_MARKER}\n{draft}\n{REVIEW_DRAFT_END_MARKER}"
        + weekly_note[result_match.end():]
    )
    try:
        weekly_note_path.parent.mkdir(parents=True, exist_ok=True)
        weekly_note_path.write_text(updated_note, encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to save weekly review draft to %s: %s", weekly_note_path, exc)
        return False

    logger.info("Weekly review draft saved to %s", weekly_note_path)
    return _send_review_draft(draft)


def main(target_date: datetime | date_type | str | None = None) -> bool:
    return review_draft(target_date)


if __name__ == "__main__":
    main()
