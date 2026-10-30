"""Citable evidence lines for AI planner proposal generation.

The planner may only propose items the person explicitly wrote down. Copying a
Japanese sentence out of the notes and comparing it verbatim is brittle (a
single punctuation difference fails), so this module extracts the citable
lines itself and assigns short stable IDs (``[E1]``, ``[E2]``, ...). The LLM
cites an ID instead of copying text, and validation becomes a set lookup.

Only sections that hold intentions, tasks and memos are citable. Machine
written sections (today's schedule / tasks written from Apple by
``write_today_schedule``, weather, location) and free-form reflection prose are
excluded, because inferring "what to do next" from them is exactly the noise
this gate exists to stop. A missing daily note yields no lines; the template
fallback in ``utils.reader`` is deliberately not used.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RECENT_DAYS = 7
MAX_LINES = 40
MAX_LINE_CHARS = 200
MIN_LINE_CHARS = 2

# Section headings whose body counts as a person's explicit intent. Anything
# else (reflection, habit tracker, schedule written from Apple) is not
# evidence.
CITABLE_SECTION_KEYWORDS = ("今日の目標", "今日のタスク", "メモ")

_HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)$")
_FENCE_RE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
_LINE_MARKER_RE = re.compile(
    r"^\s*(?:>\s*)*(?:[-*+]\s+)?(?:\[[ xX]\]\s*)?(?:\d+[.)]\s*)?"
)
_PLACEHOLDERS = ("<%", "{{", "await dv")
# Punctuation and spacing that carry no meaning for the quote rescue path.
_NOISE_RE = re.compile(r"[\s。、，．,.!?！？「」『』()（）\[\]【】:：;；\-–—〜~・*_`>]+")


@dataclass(frozen=True)
class EvidenceLine:
    ref: str
    date: date
    text: str


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4 :]


def _strip_code_fences(text: str) -> str:
    return _FENCE_RE.sub("", text)


def _clean_line(raw: str) -> str:
    cleaned = _LINE_MARKER_RE.sub("", raw)
    cleaned = cleaned.replace("**", "").replace("__", "")
    cleaned = cleaned.strip()
    if len(cleaned) < MIN_LINE_CHARS:
        return ""
    if any(token in cleaned for token in _PLACEHOLDERS):
        return ""
    if len(cleaned) > MAX_LINE_CHARS:
        cleaned = cleaned[: MAX_LINE_CHARS - 1].rstrip() + "…"
    return cleaned


def extract_citable_lines(text: str) -> list[str]:
    """Return lines from citable sections of one note, in document order."""
    body = _strip_code_fences(_strip_frontmatter(text))

    lines: list[str] = []
    in_citable_section = False
    for raw in body.splitlines():
        heading = _HEADING_RE.match(raw)
        if heading:
            level = len(heading.group(1))
            if level <= 2:
                title = heading.group(2)
                in_citable_section = any(
                    keyword in title for keyword in CITABLE_SECTION_KEYWORDS
                )
            continue
        if not in_citable_section:
            continue
        cleaned = _clean_line(raw)
        if cleaned:
            lines.append(cleaned)
    return lines


def _read_daily_note(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.exception("Failed to read daily note for planner evidence: %s", path)
        return ""


def collect_citable_lines(
    *,
    days: int = RECENT_DAYS,
    reference_date: date | None = None,
) -> list[EvidenceLine]:
    """Collect citable lines from the last ``days`` daily notes, newest first.

    Identical text repeated across days (habit-like items) is kept once, and
    the newest occurrence wins.
    """
    from obsidian_ai_hub.utils import reader

    if days < 1:
        raise ValueError("days must be positive")
    end = reference_date or date.today()

    evidence: list[EvidenceLine] = []
    seen: set[str] = set()
    for offset in range(days):
        day = end - timedelta(days=offset)
        try:
            content = _read_daily_note(reader.get_daily_note_path(day))
        except OSError:
            logger.exception("Failed to resolve daily note path for %s", day)
            continue
        if not content:
            continue
        for text in extract_citable_lines(content):
            key = normalize_for_match(text)
            if not key or key in seen:
                continue
            seen.add(key)
            evidence.append(
                EvidenceLine(ref=f"E{len(evidence) + 1}", date=day, text=text)
            )
            if len(evidence) >= MAX_LINES:
                return evidence
    return evidence


def normalize_for_match(text: str) -> str:
    """Normalize text for the quote rescue path (not for ID lookups)."""
    normalized = unicodedata.normalize("NFKC", text or "")
    return _NOISE_RE.sub("", normalized).casefold()


def build_evidence_index(lines: list[EvidenceLine]) -> dict[str, EvidenceLine]:
    return {line.ref: line for line in lines}


def find_line_by_quote(
    quote: str, lines: list[EvidenceLine], *, min_chars: int = 4
) -> EvidenceLine | None:
    """Rescue path: resolve a quoted fragment to a citable line when possible."""
    needle = normalize_for_match(quote)
    if len(needle) < min_chars:
        return None
    for line in lines:
        if needle in normalize_for_match(line.text):
            return line
    return None
