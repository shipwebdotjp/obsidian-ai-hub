from __future__ import annotations

import json
import logging
from typing import Optional

from obsidian_ai_hub.utils import config, llm_client, prompt
from obsidian_ai_hub import research_themes

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```")
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def _render_dedup_prompt(
    candidate_id: str,
    theme: str,
    direction: Optional[str],
    why_now: Optional[str],
    existing: list[tuple[str, dict]],
) -> str:
    lines = []
    for tid, t in existing:
        lines.append(
            f"- ID: {tid}\n  theme: {t.get('theme', '')}\n  direction: {t.get('direction', '') or '(none)'}\n  status: {t.get('status', '')}"
        )
    existing_text = "\n".join(lines) if lines else "(no similar themes found)"

    return prompt.render_prompt(
        config.BASE_DIR / "config" / "prompts" / "research_dedup_review.md",
        {
            "candidate_id": candidate_id,
            "candidate_theme": theme,
            "candidate_direction": direction or "(none)",
            "candidate_why_now": why_now or "(none)",
            "existing_list": existing_text,
        },
    )


def run_dedup_review(
    candidate_theme: str,
    candidate_direction: Optional[str] = None,
    candidate_why_now: Optional[str] = None,
    similar: list[tuple[str, float]] | None = None,
) -> dict:
    if not similar:
        return {
            "decision": "distinct",
            "target_theme_id": None,
            "related_ids": [],
            "confidence": 1.0,
            "reason": "No similar existing themes found",
            "failed": False,
        }

    theme_ids = [tid for tid, _ in similar]
    existing: list[tuple[str, dict]] = []
    for tid in theme_ids:
        t = research_themes.get_theme(tid)
        if t:
            existing.append((tid, t))

    if not existing:
        return {
            "decision": "distinct",
            "target_theme_id": None,
            "related_ids": [],
            "confidence": 1.0,
            "reason": "No existing themes resolved from similar IDs",
            "failed": False,
        }

    candidate_id = f"(候補: {candidate_theme})"
    rendered = _render_dedup_prompt(candidate_id, candidate_theme, candidate_direction, candidate_why_now, existing)

    try:
        response = llm_client.generate_llm_response(
            provider=config.RESEARCH_THEME_GENERATION_PROVIDER,
            model=config.RESEARCH_THEME_GENERATION_MODEL,
            prompt=rendered,
            temperature=0.0,
            max_tokens=2000,
        ).strip()
    except Exception as exc:
        logger.warning("LLM dedup review failed: %s", exc)
        return {
            "decision": "distinct",
            "target_theme_id": None,
            "related_ids": [],
            "confidence": 1.0,
            "reason": f"LLM call failed: {exc}",
            "failed": True,
        }

    cleaned = _strip_code_fences(response)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        logger.warning("LLM dedup response has no JSON: %s", response)
        return {
            "decision": "distinct",
            "target_theme_id": None,
            "related_ids": [],
            "confidence": 1.0,
            "reason": "LLM response was not valid JSON",
            "failed": True,
        }

    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("LLM dedup JSON parse failed: %s", exc)
        return {
            "decision": "distinct",
            "target_theme_id": None,
            "related_ids": [],
            "confidence": 1.0,
            "reason": f"JSON parse error: {exc}",
            "failed": True,
        }

    decision = data.get("decision", "distinct")
    target_id = data.get("target_theme_id")
    related_ids = data.get("related_ids", [])
    if not isinstance(related_ids, list):
        related_ids = []
    confidence = float(data.get("confidence", 0.5))
    reason = str(data.get("reason", "LLM dedup assessment"))

    if decision == "duplicate":
        if target_id and any(tid == target_id for tid, _ in similar):
            return {
                "decision": "duplicate",
                "target_theme_id": target_id,
                "related_ids": related_ids,
                "confidence": max(0.0, min(1.0, confidence)),
                "reason": reason,
                "failed": False,
            }
        logger.warning("LLM said duplicate but target_theme_id missing/invalid; treating as distinct")
        return {
            "decision": "distinct",
            "target_theme_id": None,
            "related_ids": related_ids,
            "confidence": 0.5,
            "reason": "duplicate declared but no valid target",
            "failed": True,
        }

    return {
        "decision": decision,
        "target_theme_id": None,
        "related_ids": related_ids,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": reason,
        "failed": False,
    }
