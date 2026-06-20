from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import List, Sequence

from obsidian_ai_hub.handler import add_research_theme
from obsidian_ai_hub.utils import config, extracter, llm_client, prompt
from obsidian_ai_hub.utils.reader import get_daily_note_path

logger = logging.getLogger(__name__)

RECENT_DAYS = 30
MAX_CONTEXT_NOTE_CHARS = 1200
MAX_CONTEXT_NOTE_LINES = 48
MAX_THEME_LENGTH = 80
MAX_DIRECTION_LENGTH = 140
LLM_CANDIDATE_COUNT = 5
ALLOWED_KINDS = ("deep", "adjacent", "explore")
HEADING_PATTERN = re.compile(r"(?m)^#{1,6}\s+(?P<text>.+?)\s*$")
HEADING_LINE_PATTERN = re.compile(r"^(#{1,6})\s+(?P<text>.+?)\s*$")
CHECKBOX_PATTERN = re.compile(r"^- \[[ xX]\]\s+")

PREVIEW_SECTION_KEYWORDS = (
    "今日の焦点",
    "今日の気づき・振り返り",
    "良かったこと・できたこと",
    "改善点・反省点",
    "感謝できること",
    "今日の自己吟味",
    "今日の小さな行動",
    "メモ",
    "AIによる要約",
)

@dataclass(frozen=True)
class RecentNote:
    note_date: date
    path: Path
    content: str


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


def _heading_level_and_text(line: str) -> tuple[int, str] | None:
    match = HEADING_LINE_PATTERN.match(line.strip())
    if match is None:
        return None
    return len(match.group(1)), match.group("text").strip()


def _extract_preview_lines(text: str) -> List[str]:
    lines = text.splitlines()
    collected: List[str] = []
    capture_heading_level: int | None = None
    capturing = False
    in_frontmatter = False
    in_code_block = False

    def _should_capture_heading(heading_text: str) -> bool:
        return any(keyword in heading_text for keyword in PREVIEW_SECTION_KEYWORDS)

    def _should_keep_fallback_line(stripped: str) -> bool:
        if not stripped:
            return False
        if stripped.startswith("---"):
            return False
        if stripped.startswith("```"):
            return False
        if stripped.startswith("#"):
            return False
        if stripped.startswith(">"):
            return False
        return True

    for raw_line in lines:
        stripped = raw_line.strip()

        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        heading_info = _heading_level_and_text(raw_line)
        if heading_info is not None:
            heading_level, heading_text = heading_info
            if capturing and capture_heading_level is not None and heading_level <= capture_heading_level:
                capturing = False
                capture_heading_level = None
            if _should_capture_heading(heading_text):
                capturing = True
                capture_heading_level = heading_level
            continue

        if capturing and stripped:
            collected.append(stripped)
            continue

    if collected:
        return collected[:MAX_CONTEXT_NOTE_LINES]

    fallback: List[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not _should_keep_fallback_line(stripped):
            continue
        fallback.append(stripped)
        if len(fallback) >= MAX_CONTEXT_NOTE_LINES:
            break
    return fallback


def _load_recent_notes(*, as_of: date | None = None, days: int = RECENT_DAYS) -> List[RecentNote]:
    reference_date = as_of or date.today()
    notes: List[RecentNote] = []

    for delta in range(days):
        note_date = reference_date - timedelta(days=delta)
        path = get_daily_note_path(note_date)
        if not path.exists():
            continue
        notes.append(
            RecentNote(
                note_date=note_date,
                path=path,
                content=path.read_text(encoding="utf-8"),
            )
        )

    notes.sort(key=lambda note: note.note_date, reverse=True)
    return notes


def _normalize_kind(kind: object) -> str:
    return _normalize_text(str(kind)).lower()


def _load_existing_candidate_themes(candidate_path: Path | None = None) -> List[str]:
    target_path = candidate_path or config.RESEARCH_CANDIDATE_THEME_LIST_PATH
    if not target_path.exists():
        return []

    themes: List[str] = []
    for line in target_path.read_text(encoding="utf-8").splitlines():
        if not CHECKBOX_PATTERN.match(line):
            continue
        payload = CHECKBOX_PATTERN.sub("", line, count=1).strip()
        if not payload:
            continue
        theme = payload.rsplit(" / ", 1)[0].strip()
        if theme:
            themes.append(theme)
    return themes


def _build_context_pack(notes: Sequence[RecentNote]) -> str:
    blocks: List[str] = []
    for note in notes:
        title = extracter.get_frontmatter_value(note.content, "title")
        if not isinstance(title, str) or not title.strip():
            heading_match = HEADING_PATTERN.search(note.content)
            title = heading_match.group("text") if heading_match else note.path.stem

        body_lines = _extract_preview_lines(note.content)

        block_lines = [
            f"- {note.note_date.isoformat()} | {title}",
        ]
        if body_lines:
            preview = _truncate_text(" / ".join(body_lines), MAX_CONTEXT_NOTE_CHARS)
            block_lines.append(f"  preview: {preview}")
        blocks.append("\n".join(block_lines))

    return "\n\n".join(blocks)


def _build_existing_candidate_block(themes: Sequence[str]) -> str:
    if not themes:
        return "(none)"
    return "\n".join(f"- {theme}" for theme in themes[:50])


def _build_llm_prompt(context_pack: str, existing_candidates: Sequence[str]) -> str:
    return prompt.render_prompt(
        config.RESEARCH_THEME_GENERATION_PROMPT_PATH,
        {
            "LLM_CANDIDATE_COUNT": LLM_CANDIDATE_COUNT,
            "context_pack": context_pack,
            "existing_candidates_block": _build_existing_candidate_block(existing_candidates),
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
    return _normalize_text(theme).casefold()


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
    notes: Sequence[RecentNote],
    existing_candidates: Sequence[str],
    as_of: date | None = None,
) -> List[SuggestedResearchTheme]:
    if not notes:
        return []

    context_pack = _build_context_pack(notes)
    prompt = _build_llm_prompt(context_pack, existing_candidates)
    existing_keys = {_candidate_key(theme) for theme in existing_candidates}
    logger.info("LLM candidate generation prompt:\n%s", prompt)

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = llm_client.generate_llm_response(
                provider="openai",
                model=config.RESEARCH_PROMPT_MODEL,
                prompt=prompt,
                temperature=config.RESEARCH_PROMPT_TEMPERATURE,
                max_tokens=config.RESEARCH_PROMPT_MAX_TOKENS,
            ).strip()
            payload = _extract_json_payload(response)
            logger.info("LLM candidate generation response payload:\n%s", json.dumps(payload, ensure_ascii=False, indent=2))
            raw_candidates = payload.get("candidates", [])
            if not isinstance(raw_candidates, list):
                raise ValueError("LLM response 'candidates' must be a list")

            parsed: List[SuggestedResearchTheme] = []
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
                prompt = prompt + "\n\nJSON のみを返してください。余計な説明やコードフェンスは不要です。"

    if last_error is not None:
        logger.exception("LLM candidate generation failed; using fallback themes")
    return []


def _select_final_suggestions(
    llm_candidates: Sequence[SuggestedResearchTheme],
    existing_candidates: Sequence[str],
) -> List[SuggestedResearchTheme]:
    existing_keys = {_candidate_key(theme) for theme in existing_candidates}
    selected: List[SuggestedResearchTheme] = []
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


def build_suggestions(*, as_of: date | None = None) -> List[SuggestedResearchTheme]:
    notes = _load_recent_notes(as_of=as_of)
    existing_candidates = _load_existing_candidate_themes()

    llm_candidates = _build_llm_candidates(
        notes=notes,
        existing_candidates=existing_candidates,
        as_of=as_of,
    )
    suggestions = _select_final_suggestions(llm_candidates, existing_candidates)

    return suggestions


def append_suggestions(
    suggestions: Sequence[SuggestedResearchTheme],
    candidate_path: Path | None = None,
) -> Path:
    target_path = candidate_path or config.RESEARCH_CANDIDATE_THEME_LIST_PATH
    for suggestion in suggestions:
        add_research_theme.append_research_theme(
            suggestion.theme,
            target_path,
            direction=suggestion.direction,
        )
    return target_path


def main(*, as_of: date | None = None) -> List[SuggestedResearchTheme]:
    suggestions = build_suggestions(as_of=as_of)
    append_suggestions(suggestions)
    for suggestion in suggestions:
        logger.info(
            "Suggested research theme (%s): %s / %s%s",
            suggestion.kind,
            suggestion.theme,
            suggestion.direction,
            f" / {suggestion.why_now}" if suggestion.why_now else "",
        )
    return suggestions
