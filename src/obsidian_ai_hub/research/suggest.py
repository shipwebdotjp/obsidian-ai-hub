from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Sequence

from obsidian_ai_hub.utils import config, llm_client, prompt

logger = logging.getLogger(__name__)

RECENT_DAYS = 30
MAX_CONTEXT_NOTE_CHARS = 1200
MAX_CONTEXT_NOTE_LINES = 48
MAX_THEME_LENGTH = 80
MAX_DIRECTION_LENGTH = 140
LLM_CANDIDATE_COUNT = 1
ALLOWED_KINDS = ("deep", "adjacent", "explore")


@dataclass(frozen=True)
class _ExistingThemeRef:
    theme: str
    status: str
    key: str  # normalized_key from DB


@dataclass(frozen=True)
class SuggestedResearchTheme:
    kind: str
    theme: str
    direction: str
    why_now: str = ""
    confidence: float = 0.0


def _normalize_text(text: str) -> str:
    return text.replace("\r", " ").replace("\n", " ").strip()


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _build_context_pack() -> str:
    from obsidian_ai_hub.research import db
    try:
        entries = db.list_recent_activity_days(days=RECENT_DAYS)
    except Exception:
        logger.exception("Failed to load activity entries")
        return ""

    if not entries:
        return ""

    blocks: list[str] = []
    for e in entries:
        summary = _truncate_text(e.get("summary", "")[:MAX_CONTEXT_NOTE_CHARS], MAX_CONTEXT_NOTE_CHARS)
        category = e.get("category", "") or ""
        keywords = ", ".join(e.get("keywords", []) or [])
        date_str = e.get("activity_date", "")
        lines = [f"- {date_str} | {summary}"]
        if category:
            lines.append(f"  category: {category}")
        if keywords:
            kw_trunc = keywords[:MAX_CONTEXT_NOTE_CHARS]
            lines.append(f"  keywords: {kw_trunc}")
        blocks.append("\n".join(lines))

        if len(blocks) >= MAX_CONTEXT_NOTE_LINES:
            break

    return "\n\n".join(blocks)


def _load_existing_db_themes() -> list[_ExistingThemeRef]:
    from obsidian_ai_hub.research import db
    try:
        themes = db.list_themes()
        return [
            _ExistingThemeRef(
                theme=t["theme"],
                status=t["status"],
                key=t["normalized_key"],
            )
            for t in themes[:50]
            if t.get("theme") and t.get("normalized_key")
        ]
    except Exception:
        logger.exception("Failed to load research themes from DB")
        return []


def _build_existing_themes_block(themes: Sequence[_ExistingThemeRef]) -> str:
    if not themes:
        return "(none)"
    lines = [f"- [{t.status}] {t.theme}" for t in themes[:50]]
    return "\n".join(lines)


def _build_llm_prompt(existing_themes: Sequence[_ExistingThemeRef]) -> str:
    context_pack = _build_context_pack()
    if not context_pack:
        return ""
    return prompt.render_prompt(
        config.RESEARCH_THEME_GENERATION_PROMPT_PATH,
        {
            "LLM_CANDIDATE_COUNT": LLM_CANDIDATE_COUNT,
            "context_pack": context_pack,
            "existing_themes_block": _build_existing_themes_block(existing_themes),
        }
    )


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


def _normalize_candidate_text(text: object) -> str:
    return _normalize_text(str(text)) if text is not None else ""


def _parse_confidence(value: object) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence < 0.0:
        return 0.0
    if confidence > 1.0:
        return 1.0
    return confidence


def _candidate_key(theme: str) -> str:
    from obsidian_ai_hub.research import db
    return db.normalize_theme_key(theme)


def _normalize_kind(kind: object) -> str:
    return _normalize_text(str(kind)).lower()


def _validate_llm_candidate(
    item: object,
    *,
    existing_keys: set[str],
    seen_keys: set[str],
) -> SuggestedResearchTheme | None:
    if not isinstance(item, dict):
        return None

    kind = _normalize_kind(item.get("kind"))
    if kind not in ALLOWED_KINDS:
        return None

    theme = _normalize_candidate_text(item.get("theme"))
    direction = _normalize_candidate_text(item.get("direction"))
    why_now = _normalize_candidate_text(item.get("why_now"))
    confidence = _parse_confidence(item.get("confidence"))

    if not theme or not direction:
        return None
    if len(theme) > MAX_THEME_LENGTH or len(direction) > MAX_DIRECTION_LENGTH:
        return None

    key = _candidate_key(theme)
    if key in existing_keys or key in seen_keys:
        return None

    seen_keys.add(key)
    return SuggestedResearchTheme(
        kind=kind,
        theme=theme,
        direction=direction,
        why_now=why_now,
        confidence=confidence,
    )


def _build_llm_candidates(
    *,
    existing_themes: Sequence[_ExistingThemeRef],
) -> list[SuggestedResearchTheme]:
    prompt_text = _build_llm_prompt(existing_themes)
    if not prompt_text:
        logger.warning("No activity context available")
        return []

    existing_keys = {t.key for t in existing_themes}
    logger.info("LLM candidate generation prompt:\n%s", prompt_text)

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = llm_client.generate_llm_response(
                provider=config.RESEARCH_THEME_GENERATION_PROVIDER,
                model=config.RESEARCH_THEME_GENERATION_MODEL,
                prompt=prompt_text,
                temperature=0.2,
                max_tokens=8000,
            ).strip()
            payload = _extract_json_payload(response)
            logger.info("LLM candidate generation response payload:\n%s", json.dumps(payload, ensure_ascii=False, indent=2))
            raw_candidates = payload.get("candidates", [])
            if not isinstance(raw_candidates, list):
                raise ValueError("LLM response 'candidates' must be a list")

            parsed: list[SuggestedResearchTheme] = []
            seen_keys: set[str] = set()
            for item in raw_candidates:
                candidate = _validate_llm_candidate(
                    item,
                    existing_keys=existing_keys,
                    seen_keys=seen_keys,
                )
                if candidate is not None:
                    parsed.append(candidate)

            if parsed:
                return parsed
            raise ValueError("LLM returned no valid candidates")
        except Exception as exc:
            last_error = exc
            logger.warning("LLM candidate generation failed on attempt %s: %s", attempt + 1, exc)
            if attempt == 0:
                prompt_text = prompt_text + "\n\nJSON のみを返してください。余計な説明やコードフェンスは不要です。"

    if last_error is not None:
        logger.exception("LLM candidate generation failed; using fallback themes")
    return []


def _select_final_suggestions(
    llm_candidates: Sequence[SuggestedResearchTheme],
    existing_themes: Sequence[_ExistingThemeRef],
) -> list[SuggestedResearchTheme]:
    existing_keys = {t.key for t in existing_themes}
    selected: list[SuggestedResearchTheme] = []
    seen_keys: set[str] = set(existing_keys)

    def _take(candidate: SuggestedResearchTheme) -> bool:
        key = _candidate_key(candidate.theme)
        if key in seen_keys:
            return False
        seen_keys.add(key)
        selected.append(candidate)
        return True

    for kind in ALLOWED_KINDS:
        best: SuggestedResearchTheme | None = None
        for candidate in llm_candidates:
            if candidate.kind != kind:
                continue
            if _candidate_key(candidate.theme) in seen_keys:
                continue
            if best is None or candidate.confidence > best.confidence:
                best = candidate
        if best is not None:
            _take(best)

    if len(selected) < 3:
        sorted_candidates = sorted(
            llm_candidates,
            key=lambda item: (item.confidence, ALLOWED_KINDS.index(item.kind) if item.kind in ALLOWED_KINDS else 99),
            reverse=True,
        )
        for candidate in sorted_candidates:
            if len(selected) >= 3:
                break
            _take(candidate)

    return selected


def build_suggestions() -> list[SuggestedResearchTheme]:
    existing_themes = _load_existing_db_themes()
    llm_candidates = _build_llm_candidates(
        existing_themes=existing_themes,
    )
    suggestions = _select_final_suggestions(llm_candidates, existing_themes)
    return suggestions


def main() -> list[dict]:
    from obsidian_ai_hub.research.pipeline import create_theme_and_research

    suggestions = build_suggestions()
    results: list[dict] = []

    for s in suggestions:
        result = create_theme_and_research(
            theme=s.theme,
            direction=s.direction,
            kind=s.kind,
            why_now=s.why_now,
            confidence=s.confidence,
        )
        results.append(result)
        logger.info(
            "Suggested research theme (%s): %s / %s%s  => %s",
            s.kind,
            s.theme,
            s.direction,
            f" / {s.why_now}" if s.why_now else "",
            result["status"],
        )

    return results
