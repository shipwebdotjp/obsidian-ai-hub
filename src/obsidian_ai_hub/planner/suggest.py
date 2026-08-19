"""AI planner proposal generation.

Generates up to LLM_CANDIDATE_COUNT low-to-medium confidence proposals from the
app's full context once a day (06:00). Candidates are validated, deduplicated
against active proposals by fingerprint, and persisted to planner_proposals.
Proposals are never written to Apple automatically; a human must edit/reject or
promote them on the Planner screen.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from obsidian_ai_hub.planner import context, store
from obsidian_ai_hub.utils import config, llm_client, prompt

logger = logging.getLogger(__name__)

LLM_CANDIDATE_COUNT = 10
GENERATION_SOURCE = "daily_06:00"
MAX_TITLE_LENGTH = 80
MAX_RATIONALE_LENGTH = 400


@dataclass(frozen=True)
class PlannerProposalCandidate:
    kind: str
    title: str
    rationale: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    due_date: Optional[str] = None


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _extract_json_payload(text: str) -> dict[str, object]:
    cleaned = _strip_code_fences(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response does not contain a JSON object")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM response JSON must be an object")
    return payload


def _normalize_text(text: object) -> str:
    return str(text).replace("\r", " ").replace("\n", " ").strip() if text is not None else ""


def _parse_iso(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    try:
        datetime.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"Invalid ISO datetime: {value}")
    return value.strip()


def _validate_candidate(item: object) -> Optional[PlannerProposalCandidate]:
    if not isinstance(item, dict):
        return None

    kind = _normalize_text(item.get("kind")).lower()
    if kind not in store.ALLOWED_KINDS:
        return None

    title = _normalize_text(item.get("title"))
    rationale = _normalize_text(item.get("rationale"))
    if not title or not rationale:
        return None
    if len(title) > MAX_TITLE_LENGTH or len(rationale) > MAX_RATIONALE_LENGTH:
        return None

    try:
        if kind == "calendar":
            start_time = _parse_iso(item.get("start_time"))
            end_time = _parse_iso(item.get("end_time"))
            if start_time is None:
                return None
            if end_time is not None and datetime.fromisoformat(end_time) < datetime.fromisoformat(start_time):
                return None
            location = _normalize_text(item.get("location")) or None
            return PlannerProposalCandidate(
                kind=kind,
                title=title,
                rationale=rationale,
                start_time=start_time,
                end_time=end_time,
                location=location,
            )
        due_date = _parse_iso(item.get("due_date"))
        return PlannerProposalCandidate(
            kind=kind,
            title=title,
            rationale=rationale,
            due_date=due_date,
        )
    except ValueError:
        return None


def _build_llm_prompt() -> str:
    context_pack = context.build_planner_context_pack()
    if not context_pack:
        logger.warning("No planner context available; generation will be thin")
    return prompt.render_prompt(
        config.AI_PLANNER_PROMPT_PATH,
        {
            "LLM_CANDIDATE_COUNT": LLM_CANDIDATE_COUNT,
            "context_pack": context_pack or "(none)",
            "excluded_inbox_items": context.build_excluded_inbox_items(),
            "existing_proposals_block": context.build_existing_proposals_block(),
        },
    )


def _persist_candidates(raw_candidates: list, source: str) -> list[dict]:
    created: list[dict] = []
    for item in raw_candidates:
        candidate = _validate_candidate(item)
        if candidate is None:
            continue
        try:
            proposal = store.create_proposal(
                kind=candidate.kind,
                title=candidate.title,
                rationale=candidate.rationale,
                generation_source=source,
                start_time=candidate.start_time,
                end_time=candidate.end_time,
                location=candidate.location,
                due_date=candidate.due_date,
            )
            created.append(proposal)
        except store.DuplicateActiveProposalError:
            logger.info("Skipped duplicate planner proposal: %s", candidate.title)
            continue
    return created


def generate_proposals(source: str = GENERATION_SOURCE) -> list[dict]:
    """Generate and persist up to LLM_CANDIDATE_COUNT proposals.

    `source` labels the origin of the generated proposals (defaults to the
    daily 06:00 scheduled job; on-demand web calls pass "manual"). Returns the
    list of created proposal dicts (duplicates are skipped).
    """
    prompt_text = _build_llm_prompt()
    logger.info("AI planner generation prompt:\n%s", prompt_text)

    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            response = llm_client.generate_llm_response(
                provider=config.AI_PLANNER_PROVIDER,
                model=config.AI_PLANNER_MODEL,
                prompt=prompt_text,
                temperature=0.2,
                max_tokens=8000,
            ).strip()
            payload = _extract_json_payload(response)
            logger.info(
                "AI planner generation response payload:\n%s",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
            raw_candidates = payload.get("candidates", [])
            if not isinstance(raw_candidates, list):
                raise ValueError("LLM response 'candidates' must be a list")
            created = _persist_candidates(raw_candidates, source)
            if created:
                return created
            raise ValueError("LLM returned no valid planner candidates")
        except Exception as exc:
            last_error = exc
            logger.warning(
                "AI planner generation failed on attempt %s: %s", attempt + 1, exc
            )
            if attempt == 0:
                prompt_text = (
                    prompt_text
                    + "\n\nJSON のみを返してください。余計な説明やコードフェンスは不要です。"
                )

    if last_error is not None:
        logger.exception("AI planner generation failed")
    return []


def main() -> list[dict]:
    proposals = generate_proposals()
    for p in proposals:
        logger.info("Created planner proposal: %s (%s) => %s", p["title"], p["kind"], p["proposal_id"])
    try:
        from obsidian_ai_hub.line_notification.planner import notify_planner_summary

        notify_planner_summary(proposals)
    except Exception:
        logger.exception("Planner LINE notification failed")
    return proposals