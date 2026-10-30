"""AI planner proposal generation.

Zero candidates is the normal outcome. A candidate is only saved when it cites
a citable evidence line (``[E1]``, ...) that this module extracted from the
user's daily notes, so proposals can no longer be invented from activity logs
or inferred from technical work records. Candidates without a resolvable
reference are dropped instead of being saved.

Stale proposals (anchor date in the past, or older than
``MAX_PROPOSAL_AGE_DAYS``) are expired before generating, so the Planner screen
does not accumulate noise. Proposals are never written to Apple automatically;
a human must edit/reject or promote them on the Planner screen.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from obsidian_ai_hub.planner import context, notes, store
from obsidian_ai_hub.utils import config, llm_client, prompt

logger = logging.getLogger(__name__)

LLM_CANDIDATE_COUNT = 3
GENERATION_SOURCE = "daily_06:00"
MAX_TITLE_LENGTH = 80
MAX_RATIONALE_LENGTH = 400
MAX_PROPOSAL_AGE_DAYS = 30

# Drop reasons recorded for observability. Zero created candidates is a normal
# outcome; these counters make "nothing was proposed" explainable.
DROP_INVALID_SHAPE = "invalid_shape"
DROP_BAD_KIND = "bad_kind"
DROP_MISSING_FIELD = "missing_field"
DROP_TOO_LONG = "too_long"
DROP_BAD_DATETIME = "bad_datetime"
DROP_EVIDENCE_MISSING = "evidence_missing"
DROP_REF_NOT_FOUND = "ref_not_found"
DROP_DUPLICATE_ACTIVE = "duplicate_active"
DROP_PAST_ANCHOR = "past_anchor"


@dataclass(frozen=True)
class PlannerProposalCandidate:
    kind: str
    title: str
    rationale: str
    evidence_ref: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    due_date: Optional[str] = None


@dataclass
class GenerationResult:
    """Outcome of one generation attempt."""

    created: list[dict] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    candidates: list[dict] = field(default_factory=list)
    skipped: Optional[str] = None


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
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if not isinstance(value, str):
        raise ValueError(f"Invalid ISO datetime: {value!r}")
    try:
        datetime.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"Invalid ISO datetime: {value}")
    return value.strip()


def _is_past_anchor(value: str) -> bool:
    """Return True when the candidate's date is before today (JST).

    Proposals dated in the past are expired by ``expire_stale_proposals`` on
    the next run, so creating them only produces noise. The prompt asks for a
    date on/after today; this is the deterministic backstop.
    """
    anchor_date = datetime.fromisoformat(value).date()
    return anchor_date < datetime.now(store.JST).date()


def _resolve_evidence_ref(
    item: dict[str, Any], evidence_index: dict[str, notes.EvidenceLine]
) -> Optional[notes.EvidenceLine]:
    """Resolve the cited evidence line, or return None when it cannot be resolved.

    The primary contract is ``evidence.ref`` (an ``[E#]`` ID assigned by
    ``planner.notes``). When the model copies a quote instead, resolve it as a
    rescue path; unknown IDs never resolve.
    """
    evidence = item.get("evidence")
    if not isinstance(evidence, dict):
        return None

    ref = str(evidence.get("ref") or "").strip().upper()
    # The pack shows `[E2]`, so accept the bracketed surface form as well.
    ref = ref.strip("[] ")
    if ref:
        line = evidence_index.get(ref)
        return line

    quote = evidence.get("quote")
    if isinstance(quote, str) and quote.strip():
        return notes.find_line_by_quote(quote, list(evidence_index.values()))
    return None


def _validate_candidate(
    item: object, evidence_index: dict[str, notes.EvidenceLine]
) -> tuple[Optional[PlannerProposalCandidate], Optional[str]]:
    """Validate one raw candidate.

    Returns ``(candidate, None)`` on success and ``(None, reason)`` when the
    candidate must be dropped.
    """
    if not isinstance(item, dict):
        return None, DROP_INVALID_SHAPE

    kind = _normalize_text(item.get("kind")).lower()
    if kind not in store.ALLOWED_KINDS:
        return None, DROP_BAD_KIND

    title = _normalize_text(item.get("title"))
    rationale = _normalize_text(item.get("rationale"))
    if not title or not rationale:
        return None, DROP_MISSING_FIELD
    if len(title) > MAX_TITLE_LENGTH or len(rationale) > MAX_RATIONALE_LENGTH:
        return None, DROP_TOO_LONG

    evidence_line = _resolve_evidence_ref(item, evidence_index)
    if evidence_line is None:
        evidence = item.get("evidence")
        has_ref = isinstance(evidence, dict) and bool(str(evidence.get("ref") or "").strip())
        return None, (DROP_REF_NOT_FOUND if has_ref else DROP_EVIDENCE_MISSING)

    try:
        if kind == "calendar":
            start_time = _parse_iso(item.get("start_time"))
            end_time = _parse_iso(item.get("end_time"))
            if start_time is None:
                return None, DROP_MISSING_FIELD
            if end_time is not None:
                try:
                    if datetime.fromisoformat(end_time) < datetime.fromisoformat(start_time):
                        return None, DROP_BAD_DATETIME
                except (ValueError, TypeError):
                    # e.g. one value offset-aware and the other naive
                    return None, DROP_BAD_DATETIME
            if _is_past_anchor(start_time):
                return None, DROP_PAST_ANCHOR
            location = _normalize_text(item.get("location")) or None
            return (
                PlannerProposalCandidate(
                    kind=kind,
                    title=title,
                    rationale=rationale,
                    evidence_ref=evidence_line.ref,
                    start_time=start_time,
                    end_time=end_time,
                    location=location,
                ),
                None,
            )
        due_date = _parse_iso(item.get("due_date"))
        if due_date is not None and _is_past_anchor(due_date):
            return None, DROP_PAST_ANCHOR
        return (
            PlannerProposalCandidate(
                kind=kind,
                title=title,
                rationale=rationale,
                evidence_ref=evidence_line.ref,
                due_date=due_date,
            ),
            None,
        )
    except ValueError:
        return None, DROP_BAD_DATETIME


def _build_llm_prompt(evidence_lines: list[notes.EvidenceLine]) -> str:
    context_pack = context.build_planner_context_pack(evidence_lines)
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


def _call_llm(prompt_text: str) -> Optional[dict[str, object]]:
    """Call the LLM, retrying once only when the response is not valid JSON."""
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
            return payload
        except Exception as exc:
            logger.warning(
                "AI planner generation returned no usable JSON on attempt %s: %s",
                attempt + 1,
                exc,
            )
            if attempt == 0:
                prompt_text = (
                    prompt_text
                    + "\n\nJSON のみを返してください。余計な説明やコードフェンスは不要です。"
                )
    logger.warning("AI planner generation failed: no usable JSON after retry")
    return None


def _persist_candidates(
    raw_candidates: list,
    source: str,
    evidence_index: dict[str, notes.EvidenceLine],
) -> tuple[list[dict], Counter]:
    created: list[dict] = []
    dropped: Counter = Counter()
    for item in raw_candidates:
        candidate, reason = _validate_candidate(item, evidence_index)
        if candidate is None:
            dropped[reason or DROP_INVALID_SHAPE] += 1
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
            dropped[DROP_DUPLICATE_ACTIVE] += 1
            logger.info("Skipped duplicate planner proposal: %s", candidate.title)
    return created, dropped


def _notify(created: list[dict]) -> None:
    if not created:
        return
    try:
        from obsidian_ai_hub.line_notification.planner import notify_planner_summary

        notify_planner_summary(created)
    except Exception as exc:
        logger.warning("Planner notification failed: %s", exc)


def run_generation(
    source: str = GENERATION_SOURCE,
    *,
    dry_run: bool = False,
) -> GenerationResult:
    """Generate candidates and (unless ``dry_run``) persist them.

    ``source`` labels the origin of the generated proposals (defaults to the
    daily 06:00 scheduled job; on-demand web calls pass "manual"). ``dry_run``
    validates the candidates and reports them without touching the database or
    sending notifications, so the evidence gate can be inspected.
    """
    if not dry_run:
        expired = store.expire_stale_proposals(max_age_days=MAX_PROPOSAL_AGE_DAYS)
        if expired:
            logger.info("Expired %s stale planner proposals", expired)

    evidence_lines = notes.collect_citable_lines()
    if not evidence_lines:
        logger.info(
            "Planner generation skipped: no citable evidence lines in recent daily notes"
        )
        return GenerationResult(skipped="no_evidence_lines")

    evidence_index = notes.build_evidence_index(evidence_lines)
    prompt_text = _build_llm_prompt(evidence_lines)
    logger.info("AI planner generation prompt:\n%s", prompt_text)

    payload = _call_llm(prompt_text)
    if payload is None:
        return GenerationResult(skipped="llm_failed")

    raw_candidates = payload.get("candidates", [])
    if not isinstance(raw_candidates, list):
        logger.warning("LLM response 'candidates' must be a list")
        return GenerationResult(skipped="bad_payload")

    if dry_run:
        candidates: list[dict] = []
        dropped: Counter = Counter()
        for item in raw_candidates:
            candidate, reason = _validate_candidate(item, evidence_index)
            if candidate is None:
                dropped[reason or DROP_INVALID_SHAPE] += 1
                continue
            candidates.append(
                {
                    "kind": candidate.kind,
                    "title": candidate.title,
                    "start_time": candidate.start_time,
                    "end_time": candidate.end_time,
                    "location": candidate.location,
                    "due_date": candidate.due_date,
                    "rationale": candidate.rationale,
                    "evidence_ref": candidate.evidence_ref,
                    "evidence_text": evidence_index[candidate.evidence_ref].text,
                }
            )
        return GenerationResult(
            created=[], dropped=dict(dropped), candidates=candidates
        )

    created, dropped = _persist_candidates(raw_candidates, source, evidence_index)
    logger.info(
        "Planner generation: created=%s dropped=%s", len(created), dict(dropped)
    )
    if source != "manual":
        _notify(created)
    return GenerationResult(created=created, dropped=dict(dropped))


def generate_proposals(source: str = GENERATION_SOURCE) -> list[dict]:
    """Generate and persist proposals.

    Returns the list of created proposal dicts. An empty list is the normal
    outcome and is not treated as a failure.
    """
    return run_generation(source).created


def main() -> dict:
    """CLI entry point: generate proposals and return a summary."""
    result = run_generation()
    for p in result.created:
        logger.info("Created planner proposal: %s (%s) => %s", p["title"], p["kind"], p["proposal_id"])
    return {
        "generated": len(result.created),
        "dropped": result.dropped,
        "skipped": result.skipped,
    }


def dry_run_main() -> dict:
    """CLI entry point: validate candidates without saving anything."""
    result = run_generation(dry_run=True)
    summary = {
        "dry_run": True,
        "candidates": len(result.candidates),
        "dropped": result.dropped,
        "skipped": result.skipped,
        "items": result.candidates,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary
