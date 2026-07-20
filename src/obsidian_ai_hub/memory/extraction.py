from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from obsidian_ai_hub.utils import config, extracter, prompt, reader
from obsidian_ai_hub.utils.embeddings import get_embedder
from obsidian_ai_hub.utils.topics import TOPIC_ENUM, normalize_topics

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.memory.dedup import (
    perform_dedup_assessment_llm,
    run_deduplication,
)
from obsidian_ai_hub.memory.models import (
    MEMORY_COLUMNS,
    _vault_relative_path,
    get_current_timestamp,
    normalize_content,
    normalize_stability,
    serialize_memory,
)
from obsidian_ai_hub.memory.store import load_all_memories, log_memory_event

logger = logging.getLogger(__name__)


def _week_bounds(
    week_date_str: Optional[str] = None,
    now: Optional[datetime] = None,
) -> tuple[datetime, datetime]:
    """Return the Monday--Sunday ISO week for an explicit date or last completed week."""
    if week_date_str:
        reference_date = datetime.strptime(week_date_str, "%Y-%m-%d")
        week_start = reference_date - timedelta(days=reference_date.weekday())
    else:
        today = now or datetime.now()
        current_week_start = today - timedelta(days=today.weekday())
        week_start = current_week_start - timedelta(days=7)
    return week_start, week_start + timedelta(days=6)


MEMORY_SOURCE_HEADERS = (
    "## 💡 今日の気づき・振り返り",
    "## 📝メモ",
)


def _extract_memory_source_content(note_content: str) -> str:
    """Return only the daily-note sections relevant to memory extraction."""
    sections = []
    for header in MEMORY_SOURCE_HEADERS:
        content = extracter.get_subheader_view(note_content, header)
        if content:
            sections.append(f"{header}\n{content}")
    return "\n\n".join(sections)


def _load_daily_structured_record(target_dt: datetime) -> dict:
    target_date_str = target_dt.strftime("%Y-%m-%d")
    try:
        from obsidian_ai_hub.summary import store as summary_store

        record = summary_store.get_summary_by_period("day", target_date_str)
    except Exception as exc:
        logger.warning(
            "Failed to load structured daily record for %s: %s", target_date_str, exc
        )
        return {}

    if not record:
        return {}

    items = record.get("items", [])
    kind_map = {
        "highlights": "highlights",
        "activities": "activities",
        "learnings": "learnings",
        "reflections": "reflections",
        "gratitude": "gratitude",
    }
    structured = {
        "date": target_date_str,
        "summary": record.get("summary"),
        "topics": record.get("topics", []),
        "people": [
            {"name": p.get("name", ""), "note": p.get("note", "")}
            for p in record.get("people", [])
        ],
        "mood": record.get("mood"),
        "sleep": record.get("sleep_raw"),
        "keywords": record.get("keywords", []),
    }
    for item in items:
        kind = item.get("kind")
        body = item.get("body")
        if kind in kind_map and body:
            structured.setdefault(kind, []).append(body)
    return structured


def _load_weekly_memory_sources(
    week_start: datetime, week_end: datetime
) -> tuple[list[dict], list[dict]]:
    daily_notes = []
    structured_records = []
    for offset in range(7):
        target_dt = week_start + timedelta(days=offset)
        note_path = reader.get_daily_note_path(target_dt)
        if note_path.exists():
            try:
                note_content = note_path.read_text(encoding="utf-8")
                daily_notes.append(
                    {
                        "date": target_dt.strftime("%Y-%m-%d"),
                        "path": _vault_relative_path(note_path),
                        "content": _extract_memory_source_content(note_content),
                    }
                )
            except OSError as exc:
                logger.warning("Failed to read daily note %s: %s", note_path, exc)

        structured_record = _load_daily_structured_record(target_dt)
        if structured_record:
            structured_records.append(structured_record)

    logger.info(
        "Loaded %s daily notes and %s structured records for %s to %s",
        len(daily_notes),
        len(structured_records),
        week_start.date(),
        week_end.date(),
    )
    return daily_notes, structured_records


def extract_memories(week_date_str: Optional[str] = None) -> list[dict]:
    """Extract memory candidates from a completed or explicitly selected week."""
    week_start, week_end = _week_bounds(week_date_str)
    week_start_str = week_start.strftime("%Y-%m-%d")
    week_end_str = week_end.strftime("%Y-%m-%d")
    logger.info("Extracting memories for week: %s to %s", week_start_str, week_end_str)

    daily_notes, structured_records = _load_weekly_memory_sources(week_start, week_end)
    if not daily_notes:
        logger.info(
            "No daily notes found for week %s to %s; skipping memory extraction",
            week_start_str,
            week_end_str,
        )
        return []

    # Build and render prompt
    rendered_prompt = prompt.render_prompt(
        config.MEMORY_EXTRACTOR_PROMPT_PATH,
        {
            "week_start": week_start_str,
            "week_end": week_end_str,
            "daily_notes": json.dumps(daily_notes, ensure_ascii=False, indent=2),
            "structured_records": json.dumps(
                structured_records, ensure_ascii=False, indent=2
            )
            if structured_records
            else "(なし)",
            "topic_candidates": json.dumps(TOPIC_ENUM, ensure_ascii=False),
        },
    )

    # Call LLM
    from obsidian_ai_hub import memory as _memory_facade

    response = _memory_facade.llm_client.generate_llm_response(
        provider=config.MEMORY_EXTRACTOR_PROVIDER,
        model=config.MEMORY_EXTRACTOR_MODEL,
        prompt=rendered_prompt,
        max_tokens=32000,
        temperature=0.2,
    ).strip()

    # Clean code blocks
    if response.startswith("```"):
        lines = response.splitlines()
        if len(lines) >= 2:
            if lines[0].startswith("```json") or lines[0].startswith("```"):
                response = "\n".join(lines[1:-1]).strip()

    try:
        extracted = json.loads(response)
        if not isinstance(extracted, list):
            extracted = [extracted]
    except json.JSONDecodeError as e:
        logger.error(
            f"Failed to parse LLM memory extraction response as JSON. Response: {response}. Error: {e}"
        )
        return []

    existing_memories = load_all_memories()
    embedder = get_embedder()

    timestamp_now = get_current_timestamp()

    class CachedEmbedder:
        def __init__(self, actual_embedder):
            self.actual_embedder = actual_embedder
            self.cache = {}

        def embed_query(self, text):
            if text not in self.cache:
                self.cache[text] = self.actual_embedder.embed_query(text)
            return self.cache[text]

    cached_embedder = CachedEmbedder(embedder) if embedder is not None else None

    # Load active approved memories
    approved_mems = [m for m in existing_memories if m.get("status") == "approved"]

    final_candidates_to_save = []
    candidates_to_assess = []
    exact_content_rejections = []

    for item in extracted:
        if not isinstance(item, dict):
            logger.warning(f"Skipping non-dict extracted candidate item: {item}")
            continue

        # Generate new ID (looked up via the facade so monkeypatching
        # `obsidian_ai_hub.memory.generate_memory_id` continues to work).
        memory_id = _memory_facade.generate_memory_id(week_end_str)

        # Build complete schema structure
        cand = {
            "schema_version": 1,
            "memory_id": memory_id,
            "status": "candidate",
            "kind": item.get("kind", "preference"),
            "memory_key": item.get("memory_key", ""),
            "content": item.get("content", ""),
            "topics": normalize_topics(item.get("topics", [])),
            "tags": item.get("tags", []),
            "evidence": item.get("evidence", []),
            "valid_from": item.get("valid_from") or week_start_str,
            "valid_until": item.get("valid_until"),
            "review_due_at": item.get("review_due_at"),
            "stability": normalize_stability(
                item.get("stability"), default="tentative"
            ),
            "sensitivity": item.get("sensitivity", "personal"),
            "extraction_confidence": float(item.get("extraction_confidence", 0.90)),
            "supersedes": item.get("supersedes"),
            "contradicts": item.get("contradicts") or [],
            "provenance": {
                "extraction_method": "weekly_llm",
                "prompt_version": "mem-extract-week-v2",
                "model": f"{config.MEMORY_EXTRACTOR_PROVIDER}:{config.MEMORY_EXTRACTOR_MODEL}",
                "week_start": week_start_str,
                "week_end": week_end_str,
            },
            "created_at": timestamp_now,
            "updated_at": timestamp_now,
            "reviewed_by": None,
            "reviewed_at": None,
            "dedup_suggestions": None,
            "dedup_assessment": None,
        }

        cand_norm = normalize_content(cand.get("content", ""))

        # 1. Check for complete normalized content match across ANY approved memory
        exact_content_matches = [
            m
            for m in approved_mems
            if normalize_content(m.get("content", "")) == cand_norm
        ]

        if exact_content_matches:
            # Duplicate: Auto-reject candidate, keep existing unchanged
            cand["status"] = "rejected"
            cand["reviewed_by"] = "system"
            cand["reviewed_at"] = timestamp_now
            cand["updated_at"] = timestamp_now

            matched_ids = [m["memory_id"] for m in exact_content_matches]
            exact_content_rejections.append((cand, matched_ids))
            final_candidates_to_save.append(cand)
            continue

        # 2. Get standard dedup suggestions using CachedEmbedder
        suggestions = run_deduplication(
            cand, existing_memories, embedder=cached_embedder
        )
        if suggestions:
            cand["dedup_suggestions"] = suggestions
            candidates_to_assess.append(cand)
        else:
            final_candidates_to_save.append(cand)

    # Perform LLM assessment on matching candidates
    perform_dedup_assessment_llm(candidates_to_assess, existing_memories)
    final_candidates_to_save.extend(candidates_to_assess)

    # Open DB connection and persist all candidates
    conn = get_db_connection()
    try:
        with conn:
            for cand in final_candidates_to_save:
                db_row = serialize_memory(cand)
                columns = ", ".join(MEMORY_COLUMNS)
                placeholders = ", ".join("?" for _ in MEMORY_COLUMNS)
                conn.execute(
                    f"INSERT INTO memories ({columns}) VALUES ({placeholders})",
                    tuple(db_row.get(col) for col in MEMORY_COLUMNS),
                )

                if cand["status"] == "rejected":
                    # Find matched IDs for exact content rejection
                    matched_ids = []
                    for c_ref, m_ids in exact_content_rejections:
                        if c_ref["memory_id"] == cand["memory_id"]:
                            matched_ids = m_ids
                            break
                    log_memory_event(
                        event_type="rejected",
                        memory_id=cand["memory_id"],
                        previous_status=None,
                        new_status="rejected",
                        changes={
                            "relation": "duplicate",
                            "target_memory_ids": matched_ids,
                        },
                        reason="内容が既存の記憶と完全に一致するため自動却下",
                        conn=conn,
                        actor="system",
                    )
                else:
                    log_memory_event(
                        event_type="created",
                        memory_id=cand["memory_id"],
                        previous_status=None,
                        new_status="candidate",
                        conn=conn,
                    )
    finally:
        conn.close()

    return final_candidates_to_save
