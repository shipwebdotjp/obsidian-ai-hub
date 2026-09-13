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


import hashlib


def compute_person_note_hash(note: str) -> str:
    """Compute sha256 hash of a person summary note string."""
    clean_text = (note or "").strip()
    return hashlib.sha256(clean_text.encode("utf-8")).hexdigest()


def _safe_extraction_confidence(value, default: float = 0.90) -> float:
    """Parse LLM-controlled confidence without aborting the batch."""
    try:
        if value is None:
            return default
        parsed = float(value)
    except (TypeError, ValueError):
        logger.warning("Invalid extraction_confidence %r; using default %s", value, default)
        return default
    if parsed != parsed or parsed == float("inf") or parsed == float("-inf"):
        logger.warning("Non-finite extraction_confidence %r; using default %s", value, default)
        return default
    return parsed


def extract_person_memories(week_date_str: Optional[str] = None) -> list[dict]:
    """Extract person memory candidates from daily summary person notes.

    Supports initial backfill and weekly incremental/resumable batch processing.
    """
    conn = get_db_connection()
    try:
        if week_date_str:
            w_start, w_end = _week_bounds(week_date_str)
            target_weeks = [(w_start, w_end)]
        else:
            # Query all daily summaries containing summary_people
            cur = conn.cursor()
            cur.execute(
                """
                SELECT s.period_key, s.summary_id, sp.person_id, sp.note, psl.content_hash
                FROM summaries s
                JOIN summary_people sp ON s.summary_id = sp.summary_id
                LEFT JOIN person_summary_extraction_logs psl
                    ON s.summary_id = psl.summary_id AND sp.person_id = psl.person_id
                WHERE s.period_type = 'day' AND sp.note IS NOT NULL AND TRIM(sp.note) != ''
                ORDER BY s.period_key ASC
                """
            )
            rows = cur.fetchall()

            unprocessed_dates = set()
            for r in rows:
                note_hash = compute_person_note_hash(r["note"])
                if r["content_hash"] != note_hash:
                    unprocessed_dates.add(r["period_key"])

            if not unprocessed_dates:
                logger.info("No unprocessed or updated daily person notes found for person memory extraction")
                return []

            # Group unprocessed dates into ISO weeks
            week_map = {}
            for d_str in sorted(unprocessed_dates):
                try:
                    dt = datetime.strptime(d_str, "%Y-%m-%d")
                    w_start, w_end = _week_bounds(d_str, now=dt)
                    w_key = w_start.strftime("%Y-%m-%d")
                    if w_key not in week_map:
                        week_map[w_key] = (w_start, w_end)
                except ValueError:
                    continue
            target_weeks = [week_map[k] for k in sorted(week_map.keys())]

        all_created_candidates = []
        for w_start, w_end in target_weeks:
            w_start_str = w_start.strftime("%Y-%m-%d")
            w_end_str = w_end.strftime("%Y-%m-%d")
            logger.info("Processing person memory extraction for week: %s to %s", w_start_str, w_end_str)

            cur = conn.cursor()
            cur.execute(
                """
                SELECT s.summary_id, s.period_key, sp.person_id, p.display_name, sp.note, psl.content_hash
                FROM summaries s
                JOIN summary_people sp ON s.summary_id = sp.summary_id
                JOIN people p ON sp.person_id = p.person_id
                LEFT JOIN person_summary_extraction_logs psl
                    ON s.summary_id = psl.summary_id AND sp.person_id = psl.person_id
                WHERE s.period_type = 'day'
                  AND s.period_key >= ? AND s.period_key <= ?
                  AND sp.note IS NOT NULL AND TRIM(sp.note) != ''
                ORDER BY s.period_key ASC, p.display_name ASC
                """,
                (w_start_str, w_end_str),
            )
            rows = cur.fetchall()

            week_entries_to_process = []
            for r in rows:
                chash = compute_person_note_hash(r["note"])
                if r["content_hash"] != chash:
                    week_entries_to_process.append({
                        "summary_id": r["summary_id"],
                        "date": r["period_key"],
                        "person_id": r["person_id"],
                        "display_name": r["display_name"],
                        "note": r["note"],
                        "content_hash": chash,
                    })

            if not week_entries_to_process:
                logger.info("Week %s to %s has no new/modified person notes; skipping", w_start_str, w_end_str)
                continue

            person_notes_payload = []
            for entry in week_entries_to_process:
                person_notes_payload.append({
                    "date": entry["date"],
                    "person_id": entry["person_id"],
                    "display_name": entry["display_name"],
                    "note": entry["note"],
                })

            rendered_prompt = prompt.render_prompt(
                config.PERSON_MEMORY_EXTRACTOR_PROMPT_PATH,
                {
                    "week_start": w_start_str,
                    "week_end": w_end_str,
                    "person_notes": json.dumps(person_notes_payload, ensure_ascii=False, indent=2),
                    "topic_candidates": json.dumps(TOPIC_ENUM, ensure_ascii=False),
                },
            )

            from obsidian_ai_hub import memory as _memory_facade

            response = _memory_facade.llm_client.generate_llm_response(
                provider=config.MEMORY_EXTRACTOR_PROVIDER,
                model=config.MEMORY_EXTRACTOR_MODEL,
                prompt=rendered_prompt,
                max_tokens=32000,
                temperature=0.2,
            ).strip()

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
                    "Failed to parse LLM person memory extraction response as JSON for week %s to %s. Response: %s. Error: %s",
                    w_start_str, w_end_str, response, e
                )
                continue

            valid_person_ids_in_week = {e["person_id"] for e in week_entries_to_process}

            existing_memories = load_all_memories()
            timestamp_now = get_current_timestamp()

            final_candidates = []
            for item in extracted:
                if not isinstance(item, dict):
                    continue
                raw_p_ids = item.get("person_ids") or []
                if not isinstance(raw_p_ids, list):
                    raw_p_ids = [raw_p_ids]
                target_p_ids = list(dict.fromkeys(pid for pid in raw_p_ids if pid in valid_person_ids_in_week))
                if not target_p_ids:
                    logger.warning("Person memory extraction returned candidate with invalid/unmatched person_ids: %s", raw_p_ids)
                    continue

                memory_id = _memory_facade.generate_memory_id(w_end_str)
                cand = {
                    "schema_version": 1,
                    "memory_id": memory_id,
                    "status": "candidate",
                    "scope": "person",
                    "kind": item.get("kind", "fact"),
                    "memory_key": item.get("memory_key", ""),
                    "content": item.get("content", ""),
                    "topics": normalize_topics(item.get("topics", [])),
                    "tags": item.get("tags", []),
                    "evidence": item.get("evidence", []),
                    "valid_from": item.get("valid_from") or w_start_str,
                    "valid_until": item.get("valid_until"),
                    "review_due_at": item.get("review_due_at"),
                    "stability": normalize_stability(item.get("stability"), default="tentative"),
                    "sensitivity": item.get("sensitivity", "personal"),
                    "extraction_confidence": _safe_extraction_confidence(item.get("extraction_confidence", 0.90)),
                    "supersedes": item.get("supersedes"),
                    "contradicts": item.get("contradicts") or [],
                    "provenance": {
                        "extraction_method": "weekly_person_llm",
                        "prompt_version": "person-mem-extract-v1",
                        "model": f"{config.MEMORY_EXTRACTOR_PROVIDER}:{config.MEMORY_EXTRACTOR_MODEL}",
                        "week_start": w_start_str,
                        "week_end": w_end_str,
                    },
                    "created_at": timestamp_now,
                    "updated_at": timestamp_now,
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "dedup_suggestions": None,
                    "dedup_assessment": None,
                    "people": [{"person_id": pid, "display_name": ""} for pid in target_p_ids],
                }

                cand_norm = normalize_content(cand.get("content", ""))
                # Deduplicate against person memories sharing target people
                shared_person_mems = [
                    m for m in existing_memories
                    if m.get("scope") == "person"
                    and m.get("status") == "approved"
                    and any(p.get("person_id") in target_p_ids for p in (m.get("people") or []))
                ]
                exact_content_matches = [
                    m for m in shared_person_mems
                    if normalize_content(m.get("content", "")) == cand_norm
                ]
                if exact_content_matches:
                    cand["status"] = "rejected"
                    cand["reviewed_by"] = "system"
                    cand["reviewed_at"] = timestamp_now
                    cand["updated_at"] = timestamp_now

                final_candidates.append(cand)

            # Atomically commit candidate memories & extraction log for this week
            with conn:
                for cand in final_candidates:
                    db_row = serialize_memory(cand)
                    columns = ", ".join(MEMORY_COLUMNS)
                    placeholders = ", ".join("?" for _ in MEMORY_COLUMNS)
                    conn.execute(
                        f"INSERT INTO memories ({columns}) VALUES ({placeholders})",
                        tuple(db_row.get(col) for col in MEMORY_COLUMNS),
                    )
                    p_ids = [p["person_id"] for p in cand["people"]]
                    for pid in p_ids:
                        conn.execute(
                            "INSERT INTO memory_people (memory_id, person_id, created_at) VALUES (?, ?, ?)",
                            (cand["memory_id"], pid, timestamp_now),
                        )

                    log_memory_event(
                        event_type="rejected" if cand["status"] == "rejected" else "created",
                        memory_id=cand["memory_id"],
                        previous_status=None,
                        new_status=cand["status"],
                        reason="内容が既存の人物記憶と完全に一致するため自動却下" if cand["status"] == "rejected" else None,
                        conn=conn,
                        actor="system" if cand["status"] == "rejected" else "user",
                    )

                # Record extraction log hashes for processed entries
                for entry in week_entries_to_process:
                    conn.execute(
                        """
                        INSERT INTO person_summary_extraction_logs (summary_id, person_id, content_hash, processed_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(summary_id, person_id) DO UPDATE SET
                            content_hash = excluded.content_hash,
                            processed_at = excluded.processed_at
                        """,
                        (entry["summary_id"], entry["person_id"], entry["content_hash"], timestamp_now),
                    )

            all_created_candidates.extend(final_candidates)

        return all_created_candidates
    finally:
        conn.close()


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
            "extraction_confidence": _safe_extraction_confidence(item.get("extraction_confidence", 0.90)),
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

    # Also run person memory extraction
    try:
        extract_person_memories(week_date_str)
    except Exception as exc:
        logger.exception("Person memory extraction failed: %s", exc)

    return final_candidates_to_save
