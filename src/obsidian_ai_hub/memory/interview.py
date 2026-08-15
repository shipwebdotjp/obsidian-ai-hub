from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict, List

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils import config, prompt, llm_client
from obsidian_ai_hub.hitl.types import QuestionDraft
from obsidian_ai_hub.hitl.service import register_run_and_questions
from obsidian_ai_hub.hitl.dispatcher import HitlContext, HitlResult
from obsidian_ai_hub.memory.extraction import _load_weekly_memory_sources, _week_bounds
from obsidian_ai_hub.memory.context import get_currently_valid_approved_memories
from obsidian_ai_hub.memory.store import load_all_memories, log_memory_event
from obsidian_ai_hub.memory.models import (
    MEMORY_COLUMNS,
    serialize_memory,
    get_current_timestamp,
    generate_memory_id,
    normalize_content,
    normalize_stability,
)
from obsidian_ai_hub.utils.topics import normalize_topics
from obsidian_ai_hub.utils.embeddings import get_embedder
from obsidian_ai_hub.memory.dedup import perform_dedup_assessment_llm, run_deduplication

logger = logging.getLogger(__name__)


def get_next_monday_morning(now: Optional[datetime] = None) -> str:
    """
    Get the ISO-8601 string for the next Monday at 09:00:00 JST from now.
    """
    jst = timezone(timedelta(hours=9))
    if now is None:
        current = datetime.now(jst)
    else:
        if now.tzinfo is None:
            current = now.replace(tzinfo=jst)
        else:
            current = now.astimezone(jst)

    # Calculate days to next Monday
    days_ahead = 7 - current.weekday()
    if days_ahead == 0:
        days_ahead = 7

    next_monday = current + timedelta(days=days_ahead)
    next_monday = next_monday.replace(hour=9, minute=0, second=0, microsecond=0)
    return next_monday.isoformat()


def _parse_llm_json_list(response: str) -> list[dict]:
    """
    Strip response, remove optional Markdown code fence, parse JSON,
    and normalize non-list values to a list.
    """
    cleaned = response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 2:
            if lines[0].startswith("```json") or lines[0].startswith("```"):
                cleaned = "\n".join(lines[1:-1]).strip()

    parsed = json.loads(cleaned)
    if not isinstance(parsed, list):
        parsed = [parsed]
    return parsed


def compile_approved_memories_for_interview(limit_tokens: int = 4000) -> list[dict]:
    """
    Compile currently valid approved memories up to a token limit.
    """
    all_approved, _ = get_currently_valid_approved_memories()
    # Estimate tokens and filter to limit_tokens
    from obsidian_ai_hub.memory.models import estimate_tokens
    compiled = []
    current_tokens = 0
    for m in all_approved:
        # Simple representation of memory
        rep = f"- [{m.get('kind', 'fact')}] {m.get('content', '')} (Topics: {m.get('topics', [])})\n"
        tokens = estimate_tokens(rep)
        if current_tokens + tokens > limit_tokens:
            break
        compiled.append(m)
        current_tokens += tokens
    return compiled


def generate_interview_questions(week_date_str: Optional[str] = None) -> None:
    """
    Generate at most 3 personalized interview questions based on the selected week.
    If a run for the week already exists, do not regenerate.
    """
    week_start, week_end = _week_bounds(week_date_str)
    week_start_str = week_start.strftime("%Y-%m-%d")
    week_end_str = week_end.strftime("%Y-%m-%d")

    iso_year, iso_week, _ = week_end.isocalendar()
    run_id = f"mem_interview_{iso_year}-W{iso_week:02d}"

    conn = get_db_connection()
    try:
        from obsidian_ai_hub.hitl.store import get_run
        existing_run = get_run(run_id, conn)
        if existing_run:
            logger.info(f"Run {run_id} already exists. Skipping question generation.")
            return

        daily_notes, structured_records = _load_weekly_memory_sources(week_start, week_end)
        if not daily_notes:
            logger.info(f"No daily notes found for week {week_start_str} to {week_end_str}; skipping interview questions generation.")
            return

        approved_mems = compile_approved_memories_for_interview(config.MEMORY_INTERVIEW_CONTEXT_MAX_TOKENS)

        # Resolve provider/model
        provider = config.MEMORY_INTERVIEW_PROVIDER or config.MEMORY_EXTRACTOR_PROVIDER
        model = config.MEMORY_INTERVIEW_MODEL or config.MEMORY_EXTRACTOR_MODEL

        rendered_prompt = prompt.render_prompt(
            config.MEMORY_INTERVIEW_QUESTION_PROMPT_PATH,
            {
                "week_start": week_start_str,
                "week_end": week_end_str,
                "daily_notes": json.dumps(daily_notes, ensure_ascii=False, indent=2),
                "structured_records": json.dumps(structured_records, ensure_ascii=False, indent=2) if structured_records else "(なし)",
                "approved_memories": json.dumps(approved_mems, ensure_ascii=False, indent=2) if approved_mems else "(なし)",
                "max_questions": config.MEMORY_INTERVIEW_MAX_QUESTIONS,
            }
        )

        response = llm_client.generate_llm_response(
            provider=provider,
            model=model,
            prompt=rendered_prompt,
            max_tokens=16384,
            temperature=0.2,
        ).strip()

        try:
            questions_list = _parse_llm_json_list(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response for interview questions as JSON. Response: {response}. Error: {e}")
            return

        if not questions_list:
            logger.info("No questions generated by LLM.")
            return

        # Restrict to max limit
        questions_list = questions_list[:config.MEMORY_INTERVIEW_MAX_QUESTIONS]

        # Register HITL Questions
        expires_at = get_next_monday_morning()
        questions_data = []
        for idx, q_item in enumerate(questions_list):
            q_key = q_item.get("question_key")
            if not q_key:
                continue
            questions_data.append({
                "question_key": q_key,
                "question_type": "text",
                "display_text": q_item.get("prompt") or q_item.get("title") or "",
                "choices": None,
                "is_required": 1,
                "sequence": idx,
                "title": q_item.get("title"),
                "prompt": q_item.get("prompt"),
                "context_json": q_item.get("context"),
                "expires_at": expires_at,
            })

        if not questions_data:
            logger.info("No valid questions to register.")
            return

        checkpoint_data = {
            "source_week_start": week_start_str,
            "source_week_end": week_end_str,
            "provider": provider,
            "model": model,
        }

        register_run_and_questions(
            run_id=run_id,
            handler="memory.apply_interview_answers",
            checkpoint=json.dumps(checkpoint_data),
            question_set_id="initial",
            questions_data=questions_data,
            conn=conn,
            title="週次メモリインタビュー",
            description=f"{week_start_str} 〜 {week_end_str} の振り返り質問",
            display_type="interview",
        )
        logger.info(f"Successfully registered interview HITL run: {run_id}")

        # The registration transaction above has committed. Notify via LINE as a
        # best-effort push after commit and guard the whole call so a
        # notification failure never fails the registration.
        try:
            from obsidian_ai_hub.line_notification import notify_hitl_run

            notify_hitl_run(
                kind="週次メモリインタビュー",
                title="週次メモリインタビュー",
                description=f"{week_start_str} 〜 {week_end_str} の振り返り質問",
                run_id=run_id,
            )
        except Exception as exc:
            logger.warning(
                "LINE interview notification failed after commit for run %s: %s",
                run_id,
                type(exc).__name__,
            )
    finally:
        conn.close()


def apply_interview_answers(context: HitlContext) -> HitlResult:
    """
    HITL handler triggered after interview questions are answered.
    Extracts, deduplicates, and saves long-term memory candidates in an all-or-nothing transaction.
    """
    conn = context.conn
    checkpoint_str = context.checkpoint
    if not checkpoint_str:
        return HitlResult.fail("Missing checkpoint with week dates")

    try:
        checkpoint_data = json.loads(checkpoint_str)
    except Exception as e:
        return HitlResult.fail(f"Invalid checkpoint format: {e}")

    week_start_str = checkpoint_data.get("source_week_start")
    week_end_str = checkpoint_data.get("source_week_end")
    if not week_start_str or not week_end_str:
        return HitlResult.fail("Missing source_week_start or source_week_end in checkpoint")

    # Fetch active set questions to get titles, prompts, and raw answers
    from obsidian_ai_hub.hitl.store import get_questions_by_set, get_run
    run_record = get_run(context.run_id, conn)
    if not run_record:
        return HitlResult.fail("Run record not found")

    active_set_id = run_record["active_question_set_id"]
    questions = get_questions_by_set(context.run_id, active_set_id, conn)

    # Compile questions with non-empty text answers
    answered_questions = []
    for q in questions:
        ans_payload = context.raw_answers_by_question_key.get(q["question_key"])
        if ans_payload and isinstance(ans_payload, dict):
            user_ans = ans_payload.get("value")
            answered_at = q.get("answered_at") or get_current_timestamp()
            if user_ans and str(user_ans).strip():
                answered_questions.append((q, user_ans, answered_at))

    if not answered_questions:
        logger.info("No answered questions with non-empty values.")
        return HitlResult.complete()

    # Extract memory candidates for each answer using LLM
    provider = config.MEMORY_INTERVIEW_PROVIDER or config.MEMORY_EXTRACTOR_PROVIDER
    model = config.MEMORY_INTERVIEW_MODEL or config.MEMORY_EXTRACTOR_MODEL

    extracted_candidates = []
    for q_record, user_ans, answered_at in answered_questions:
        rendered_prompt = prompt.render_prompt(
            config.MEMORY_INTERVIEW_EXTRACTION_PROMPT_PATH,
            {
                "week_start": week_start_str,
                "week_end": week_end_str,
                "question_title": q_record.get("title") or "",
                "question_prompt": q_record.get("prompt") or "",
                "user_answer": user_ans,
            }
        )

        try:
            response = llm_client.generate_llm_response(
                provider=provider,
                model=model,
                prompt=rendered_prompt,
                max_tokens=16384,
                temperature=0.2,
            ).strip()
        except Exception as e:
            logger.error(f"LLM call failed for extracting candidate: {e}")
            return HitlResult.fail(f"LLM call failed: {e}")

        try:
            extracted = _parse_llm_json_list(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM memory extract response as JSON. Response: {response}. Error: {e}")
            return HitlResult.fail(f"JSON decode failed for extract response: {e}")

        for item in extracted:
            if not isinstance(item, dict) or not item.get("content"):
                continue

            # Safely normalize extraction_confidence
            raw_confidence = item.get("extraction_confidence")
            confidence = 0.90
            if raw_confidence is not None:
                try:
                    confidence = float(raw_confidence)
                except ValueError:
                    logger.warning(f"Invalid extraction_confidence value '{raw_confidence}', falling back to 0.90")
                    confidence = 0.90

            memory_id = generate_memory_id(week_end_str)
            cand = {
                "schema_version": 1,
                "memory_id": memory_id,
                "status": "candidate",
                "kind": item.get("kind", "preference"),
                "memory_key": item.get("memory_key", ""),
                "content": item.get("content", ""),
                "topics": normalize_topics(item.get("topics", [])),
                "tags": item.get("tags", []),
                "evidence": [{
                    "path": f"hitl://runs/{context.run_id}/questions/{q_record['question_key']}",
                    "quote": user_ans,
                    "observed_at": answered_at[:10],
                }],
                "valid_from": item.get("valid_from") or week_start_str,
                "valid_until": item.get("valid_until"),
                "review_due_at": item.get("review_due_at"),
                "stability": normalize_stability(item.get("stability"), default="tentative"),
                "sensitivity": item.get("sensitivity", "personal"),
                "extraction_confidence": confidence,
                "supersedes": item.get("supersedes"),
                "contradicts": item.get("contradicts") or [],
                "provenance": {
                    "extraction_method": "weekly_hitl_interview",
                    "prompt_version": "memory-interview-extract-v1",
                    "model": f"{provider}:{model}",
                    "source_week_start": week_start_str,
                    "source_week_end": week_end_str,
                    "hitl_run_id": context.run_id,
                    "hitl_question_key": q_record["question_key"],
                    "hitl_answered_at": answered_at,
                },
                "created_at": get_current_timestamp(),
                "updated_at": get_current_timestamp(),
                "reviewed_by": None,
                "reviewed_at": None,
                "dedup_suggestions": None,
                "dedup_assessment": None,
            }
            extracted_candidates.append(cand)

    # All LLM generations succeeded. Proceed to deduplication and DB saving
    existing_memories = load_all_memories()
    embedder = get_embedder()

    class CachedEmbedder:
        def __init__(self, actual_embedder):
            self.actual_embedder = actual_embedder
            self.cache = {}

        def embed_query(self, text):
            if text not in self.cache:
                self.cache[text] = self.actual_embedder.embed_query(text)
            return self.cache[text]

    cached_embedder = CachedEmbedder(embedder) if embedder is not None else None
    approved_mems = [m for m in existing_memories if m.get("status") == "approved"]

    final_candidates_to_save = []
    candidates_to_assess = []
    exact_content_rejections = []

    for cand in extracted_candidates:
        cand_norm = normalize_content(cand.get("content", ""))

        exact_content_matches = [
            m for m in approved_mems
            if normalize_content(m.get("content", "")) == cand_norm
        ]

        # Check in the current candidate-processing loop (including candidates already accepted in the same batch)
        # to ensure subsequent exact-content checks see previously accepted same-batch candidates.
        exact_batch_matches = [
            m for m in final_candidates_to_save
            if normalize_content(m.get("content", "")) == cand_norm
        ]

        if exact_content_matches or exact_batch_matches:
            cand["status"] = "rejected"
            cand["reviewed_by"] = "system"
            cand["reviewed_at"] = get_current_timestamp()
            cand["updated_at"] = get_current_timestamp()

            matched_ids = [m["memory_id"] for m in (exact_content_matches + exact_batch_matches)]
            exact_content_rejections.append((cand, matched_ids))
            final_candidates_to_save.append(cand)
            existing_memories.append(cand)
            continue

        suggestions = run_deduplication(
            cand, existing_memories, embedder=cached_embedder
        )
        if suggestions:
            cand["dedup_suggestions"] = suggestions
            candidates_to_assess.append(cand)
            # Add to existing memories immediately so vector/assessment checks see it
            existing_memories.append(cand)
        else:
            final_candidates_to_save.append(cand)
            existing_memories.append(cand)

    # Perform LLM assessment on the collected assessable candidates (which are already in existing_memories)
    perform_dedup_assessment_llm(candidates_to_assess, existing_memories)
    final_candidates_to_save.extend(candidates_to_assess)

    # All calculations succeeded, perform DB transaction write
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

    logger.info(f"Successfully processed {len(final_candidates_to_save)} memory candidates from interview.")
    return HitlResult.complete()
