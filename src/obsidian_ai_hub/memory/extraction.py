from __future__ import annotations

import json
import logging
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

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

JST = timezone(timedelta(hours=9))

_AGENT_EVIDENCE_PATH_PATTERN = re.compile(
    r"^agent://sessions/([A-Za-z0-9_-]{1,128})/messages/([A-Za-z0-9_-]{1,128})$"
)


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
                target_p_ids = list(dict.fromkeys(pid for pid in raw_p_ids if isinstance(pid, str) and pid in valid_person_ids_in_week))
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


class _CachedEmbedder:
    """Embed each distinct text once per extraction batch."""

    def __init__(self, actual_embedder):
        self.actual_embedder = actual_embedder
        self.cache: dict = {}

    def embed_query(self, text):
        if text not in self.cache:
            self.cache[text] = self.actual_embedder.embed_query(text)
        return self.cache[text]


def _make_cached_embedder():
    embedder = get_embedder()
    return _CachedEmbedder(embedder) if embedder is not None else None


def _parse_llm_json_array(response: str, context_label: str) -> Optional[list]:
    """Parse an LLM response expected to hold a JSON array (optionally fenced)."""
    clean = (response or "").strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        if len(lines) >= 2:
            clean = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as e:
        # The response is not logged: for the agent-conversation source it can
        # contain verbatim private chat text (candidate content and evidence).
        logger.error(
            "Failed to parse LLM %s response as JSON (length %s). Error: %s",
            context_label,
            len(clean),
            e,
        )
        return None
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        logger.error("LLM %s response was not a JSON array or object", context_label)
        return None
    return parsed


def _finalize_user_scope_candidates(
    extracted: list,
    *,
    existing_memories: list[dict],
    embedder,
    build_candidate: Callable[[dict], Optional[dict]],
    duplicate_check_statuses: frozenset[str] = frozenset({"approved"}),
    duplicate_reject_reason: str = "内容が既存の記憶と完全に一致するため自動却下",
) -> list[dict]:
    """Deduplicate, assess, and persist user-scope candidates.

    ``build_candidate`` returns a complete candidate dict for one extracted
    item, or ``None`` when the item fails source-specific validation (for
    example agent-conversation evidence that does not cite a user message).
    """
    timestamp_now = get_current_timestamp()
    reference_mems = [
        m for m in existing_memories if m.get("status") in duplicate_check_statuses
    ]

    final_candidates_to_save: list[dict] = []
    candidates_to_assess: list[dict] = []
    exact_content_rejections: list[tuple[dict, list[str]]] = []

    for item in extracted:
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict extracted candidate item: %s", item)
            continue

        cand = build_candidate(item)
        if cand is None:
            continue

        cand_norm = normalize_content(cand.get("content", ""))

        # 1. Complete normalized content match in any reference memory
        exact_content_matches = [
            m
            for m in reference_mems
            if normalize_content(m.get("content", "")) == cand_norm
        ]
        if exact_content_matches:
            cand["status"] = "rejected"
            cand["reviewed_by"] = "system"
            cand["reviewed_at"] = timestamp_now
            cand["updated_at"] = timestamp_now
            exact_content_rejections.append(
                (cand, [m["memory_id"] for m in exact_content_matches])
            )
            final_candidates_to_save.append(cand)
            continue

        # 2. Standard dedup suggestions against approved memories
        suggestions = run_deduplication(cand, existing_memories, embedder=embedder)
        if suggestions:
            cand["dedup_suggestions"] = suggestions
            candidates_to_assess.append(cand)
        else:
            final_candidates_to_save.append(cand)

    perform_dedup_assessment_llm(candidates_to_assess, existing_memories)
    final_candidates_to_save.extend(candidates_to_assess)

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
                    matched_ids = next(
                        (
                            m_ids
                            for c_ref, m_ids in exact_content_rejections
                            if c_ref["memory_id"] == cand["memory_id"]
                        ),
                        [],
                    )
                    log_memory_event(
                        event_type="rejected",
                        memory_id=cand["memory_id"],
                        previous_status=None,
                        new_status="rejected",
                        changes={
                            "relation": "duplicate",
                            "target_memory_ids": matched_ids,
                        },
                        reason=duplicate_reject_reason,
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


def extract_memories(week_date_str: Optional[str] = None) -> list[dict]:
    """Extract memory candidates from a completed or explicitly selected week."""
    week_start, week_end = _week_bounds(week_date_str)
    week_start_str = week_start.strftime("%Y-%m-%d")
    week_end_str = week_end.strftime("%Y-%m-%d")
    logger.info("Extracting memories for week: %s to %s", week_start_str, week_end_str)

    daily_notes, structured_records = _load_weekly_memory_sources(week_start, week_end)
    if not daily_notes:
        logger.info(
            "No daily notes found for week %s to %s; skipping daily-note memory extraction",
            week_start_str,
            week_end_str,
        )
        return extract_agent_conversation_memories(week_date_str)

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

    extracted = _parse_llm_json_array(
        response, f"memory extraction week {week_start_str}"
    )
    if extracted is None:
        return []

    existing_memories = load_all_memories()
    embedder = _make_cached_embedder()
    timestamp_now = get_current_timestamp()

    def build_candidate(item: dict) -> dict:
        memory_id = _memory_facade.generate_memory_id(week_end_str)
        return {
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
            "extraction_confidence": _safe_extraction_confidence(
                item.get("extraction_confidence", 0.90)
            ),
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

    final_candidates_to_save = _finalize_user_scope_candidates(
        extracted,
        existing_memories=existing_memories,
        embedder=embedder,
        build_candidate=build_candidate,
    )

    # Also run person memory extraction
    try:
        extract_person_memories(week_date_str)
    except Exception as exc:
        logger.exception("Person memory extraction failed: %s", exc)

    # Also extract candidates from Web-chat agent conversations
    final_candidates_to_save.extend(
        extract_agent_conversation_memories(week_date_str)
    )

    return final_candidates_to_save


def _utc_iso_to_jst_date(value: str) -> str:
    """Convert a stored UTC ISO timestamp to its JST calendar date."""
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Unparsable agent message timestamp %r", value)
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(JST).date().isoformat()


def _load_weekly_agent_messages(
    week_start: datetime, week_end: datetime
) -> tuple[list[dict], list[str]]:
    """Load Web-chat agent messages for the week, grouped by session.

    Returns ``(sessions, included_message_ids)``. Assistant replies are loaded
    as context only; callers must never turn them into evidence. Task Agent and
    Workflow Agent Node sessions are machine-generated, and sessions created
    before the ``source`` column existed stay NULL, so both are excluded.
    """
    if not config.MEMORY_AGENT_CONVERSATION_ENABLED:
        return [], []

    start_utc = week_start.replace(tzinfo=JST).astimezone(timezone.utc).isoformat()
    end_utc = (
        (week_end + timedelta(days=1))
        .replace(tzinfo=JST)
        .astimezone(timezone.utc)
        .isoformat()
    )

    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT m.message_id, m.session_id, m.role, m.content, m.created_at,
                   s.title AS session_title
            FROM agent_messages m
            JOIN agent_sessions s ON s.session_id = m.session_id
            WHERE s.source = 'chat'
              AND m.role IN ('user', 'assistant')
              AND m.created_at >= ? AND m.created_at < ?
              AND m.message_id NOT IN (
                  SELECT message_id FROM agent_message_extraction_logs
              )
            ORDER BY m.session_id ASC, m.sequence ASC
            """,
            (start_utc, end_utc),
        ).fetchall()
    finally:
        conn.close()

    max_messages = config.MEMORY_AGENT_CONVERSATION_MAX_MESSAGES
    max_total_chars = config.MEMORY_AGENT_CONVERSATION_MAX_TOTAL_CHARS
    max_user_chars = config.MEMORY_AGENT_CONVERSATION_MAX_USER_CHARS
    max_assistant_chars = config.MEMORY_AGENT_CONVERSATION_MAX_ASSISTANT_CHARS

    sessions: list[dict] = []
    sessions_by_id: dict[str, dict] = {}
    included_message_ids: list[str] = []
    total_chars = 0
    skipped_for_budget = 0

    for row in rows:
        content = (row["content"] or "").strip()
        if not content:
            continue
        role = str(row["role"])
        limit = max_user_chars if role == "user" else max_assistant_chars
        if limit > 0 and len(content) > limit:
            content = content[:limit] + "…"
        if (
            len(included_message_ids) >= max_messages
            or total_chars + len(content) > max_total_chars
        ):
            skipped_for_budget += 1
            continue

        session_entry = sessions_by_id.get(row["session_id"])
        if session_entry is None:
            session_entry = {
                "session_id": row["session_id"],
                "session_title": row["session_title"],
                "entries": [],
            }
            sessions_by_id[row["session_id"]] = session_entry
            sessions.append(session_entry)
        session_entry["entries"].append(
            {
                "message_id": row["message_id"],
                "role": role,
                "date": _utc_iso_to_jst_date(row["created_at"]),
                "content": content,
            }
        )
        included_message_ids.append(row["message_id"])
        total_chars += len(content)

    if skipped_for_budget:
        logger.warning(
            "Agent conversation extraction skipped %s messages for week %s to %s "
            "because the configured message/char budget was exhausted",
            skipped_for_budget,
            week_start.date(),
            week_end.date(),
        )

    # Assistant-only sessions have no extractable source; drop them and their
    # message ids so nothing from them is marked as processed.
    sessions = [
        s for s in sessions if any(e["role"] == "user" for e in s["entries"])
    ]
    retained_ids = {e["message_id"] for s in sessions for e in s["entries"]}
    included_message_ids = [mid for mid in included_message_ids if mid in retained_ids]

    return sessions, included_message_ids


def _validate_agent_conversation_evidence(
    evidence: object, user_messages: dict[str, dict]
) -> Optional[list[dict]]:
    """Keep only evidence items that cite a role=user message verbatim.

    The extractor receives assistant replies as context, so the model can
    mistakenly cite them. A candidate survives only when at least one evidence
    item resolves to a known user message and quotes its content.
    """
    if not isinstance(evidence, list):
        return None

    validated: list[dict] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        quote = item.get("quote")
        if not isinstance(path, str) or not isinstance(quote, str) or not quote.strip():
            continue
        match = _AGENT_EVIDENCE_PATH_PATTERN.match(path.strip())
        if not match:
            continue
        session_id, message_id = match.group(1), match.group(2)
        user_message = user_messages.get(message_id)
        if user_message is None or user_message["session_id"] != session_id:
            continue
        if normalize_content(quote) not in normalize_content(user_message["content"]):
            continue
        validated.append(
            {
                "path": path.strip(),
                "quote": quote.strip()[:500],
                "observed_at": item.get("observed_at") or user_message["date"],
            }
        )

    return validated or None


def extract_agent_conversation_memories(
    week_date_str: Optional[str] = None,
) -> list[dict]:
    """Extract memory candidates from Web-chat agent conversations.

    Only user utterances can become candidates. Assistant replies are sent as
    context and rejected as evidence by
    :func:`_validate_agent_conversation_evidence`.
    """
    week_start, week_end = _week_bounds(week_date_str)
    week_start_str = week_start.strftime("%Y-%m-%d")
    week_end_str = week_end.strftime("%Y-%m-%d")

    if not config.MEMORY_AGENT_CONVERSATION_ENABLED:
        logger.info("Agent conversation memory extraction is disabled")
        return []

    sessions, included_message_ids = _load_weekly_agent_messages(
        week_start, week_end
    )
    if not sessions:
        logger.info(
            "No agent chat messages found for week %s to %s; skipping",
            week_start_str,
            week_end_str,
        )
        return []

    logger.info(
        "Extracting agent conversation memories for week %s to %s (%s sessions, %s messages)",
        week_start_str,
        week_end_str,
        len(sessions),
        len(included_message_ids),
    )

    rendered_prompt = prompt.render_prompt(
        config.MEMORY_AGENT_CONVERSATION_PROMPT_PATH,
        {
            "week_start": week_start_str,
            "week_end": week_end_str,
            "sessions": json.dumps(sessions, ensure_ascii=False, indent=2),
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

    extracted = _parse_llm_json_array(
        response, f"agent conversation extraction week {week_start_str}"
    )
    if extracted is None:
        return []

    user_messages = {
        entry["message_id"]: {
            "session_id": session["session_id"],
            "content": entry["content"],
            "date": entry["date"],
        }
        for session in sessions
        for entry in session["entries"]
        if entry["role"] == "user"
    }

    existing_memories = load_all_memories()
    embedder = _make_cached_embedder()
    timestamp_now = get_current_timestamp()

    def build_candidate(item: dict) -> Optional[dict]:
        validated_evidence = _validate_agent_conversation_evidence(
            item.get("evidence"), user_messages
        )
        if validated_evidence is None:
            logger.warning(
                "Dropping agent conversation candidate without user-message evidence"
            )
            return None
        memory_id = _memory_facade.generate_memory_id(week_end_str)
        return {
            "schema_version": 1,
            "memory_id": memory_id,
            "status": "candidate",
            "kind": item.get("kind", "preference"),
            "memory_key": item.get("memory_key", ""),
            "content": item.get("content", ""),
            "topics": normalize_topics(item.get("topics", [])),
            "tags": item.get("tags", []),
            "evidence": validated_evidence,
            "valid_from": item.get("valid_from") or week_start_str,
            "valid_until": item.get("valid_until"),
            "review_due_at": item.get("review_due_at"),
            "stability": normalize_stability(
                item.get("stability"), default="tentative"
            ),
            "sensitivity": item.get("sensitivity", "personal"),
            "extraction_confidence": _safe_extraction_confidence(
                item.get("extraction_confidence", 0.90)
            ),
            "supersedes": item.get("supersedes"),
            "contradicts": item.get("contradicts") or [],
            "provenance": {
                "extraction_method": "weekly_agent_conversation_llm",
                "prompt_version": "agent-mem-extract-v1",
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

    final_candidates = _finalize_user_scope_candidates(
        extracted,
        existing_memories=existing_memories,
        embedder=embedder,
        build_candidate=build_candidate,
        duplicate_check_statuses=frozenset({"approved", "candidate"}),
    )

    # Mark every message that took part in this extraction run so reruns of the
    # same week neither resend context nor duplicate candidates.
    conn = get_db_connection()
    try:
        with conn:
            for message_id in included_message_ids:
                conn.execute(
                    """
                    INSERT INTO agent_message_extraction_logs (message_id, processed_at)
                    VALUES (?, ?)
                    ON CONFLICT(message_id) DO UPDATE SET processed_at = excluded.processed_at
                    """,
                    (message_id, timestamp_now),
                )
    finally:
        conn.close()

    return final_candidates
