"""Candidate memory proposal consolidation service.

Combines multiple candidate proposals targeting the same approved memory
into a single final candidate using LLM synthesis.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.memory.dedup import (
    perform_dedup_assessment_llm,
    run_deduplication,
)
from obsidian_ai_hub.memory.models import (
    MEMORY_COLUMNS,
    compute_memory_fingerprint,
    generate_memory_id,
    get_current_timestamp,
    serialize_memory,
)
from obsidian_ai_hub.memory.store import load_all_memories, log_memory_event
from obsidian_ai_hub.utils import config, prompt, llm_client
from obsidian_ai_hub.utils.topics import normalize_topics

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def _deduplicate_evidence(evidence_lists: list[list[dict]]) -> list[dict]:
    seen = set()
    result = []
    for ev_list in evidence_lists:
        if not isinstance(ev_list, list):
            continue
        for ev in ev_list:
            if not isinstance(ev, dict):
                continue
            path = str(ev.get("path") or "").strip()
            quote = str(ev.get("quote") or "").strip()
            key = (path, quote)
            if key not in seen:
                seen.add(key)
                result.append(ev)
    return result


def _deduplicate_tags(tag_lists: list[list[str]]) -> list[str]:
    seen = set()
    result = []
    for t_list in tag_lists:
        if not isinstance(t_list, list):
            continue
        for tag in t_list:
            if not isinstance(tag, str):
                continue
            cleaned = tag.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
                if len(result) >= 10:
                    return result
    return result


def _deduplicate_topics(topic_lists: list[list[str]]) -> list[str]:
    raw_flat = []
    for t_list in topic_lists:
        if isinstance(t_list, list):
            raw_flat.extend(t_list)
    return normalize_topics(raw_flat)


def _deduplicate_contradicts(contradict_lists: list[list[str]]) -> list[str]:
    seen = set()
    result = []
    for c_list in contradict_lists:
        if not isinstance(c_list, list):
            continue
        for item in c_list:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
    return result


def _get_min_valid_from(candidates: list[dict]) -> Optional[str]:
    valid_froms = [
        c.get("valid_from") for c in candidates if c.get("valid_from") and isinstance(c.get("valid_from"), str)
    ]
    return min(valid_froms) if valid_froms else None


def _get_max_confidence(candidates: list[dict]) -> float:
    confidences = []
    for c in candidates:
        raw = c.get("extraction_confidence")
        try:
            if raw is not None:
                confidences.append(float(raw))
        except (ValueError, TypeError):
            pass
    return max(confidences) if confidences else 0.90


def consolidate_candidate_proposals(
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Consolidate candidate proposals targeting the same approved memory.

    Finds groups of 2 or more candidate memories that target the same approved
    memory (in the same scope). Synthesizes each group into a single final
    candidate proposal, moving original candidates to `rejected` with `reviewed_by='system'`
    and a `consolidated` audit event.

    Returns the list of created consolidated candidates.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        all_memories = load_all_memories()
        approved_mems = [m for m in all_memories if m.get("status") == "approved"]
        approved_map = {m["memory_id"]: m for m in approved_mems}

        candidate_mems = [m for m in all_memories if m.get("status") == "candidate"]
        if len(candidate_mems) < 2:
            return []

        # Re-assess candidates that lack dedup_assessment or have fingerprint mismatches
        candidates_to_assess = []
        for cand in candidate_mems:
            assessment = cand.get("dedup_assessment")
            if not assessment or not isinstance(assessment, dict):
                candidates_to_assess.append(cand)
            else:
                target_id = assessment.get("target_memory_id")
                target_fp = assessment.get("target_fingerprint")
                if target_id and target_id in approved_map:
                    current_fp = compute_memory_fingerprint(approved_map[target_id])
                    if target_fp != current_fp:
                        candidates_to_assess.append(cand)

        if candidates_to_assess:
            for c in candidates_to_assess:
                sug = run_deduplication(c, approved_mems)
                c["dedup_suggestions"] = sug
            perform_dedup_assessment_llm(candidates_to_assess, approved_mems)

        # Group candidates by (scope, target_memory_id)
        groups: dict[tuple[str, str], list[dict]] = {}
        for cand in candidate_mems:
            assessment = cand.get("dedup_assessment") or {}
            decision = assessment.get("decision")
            target_id = assessment.get("target_memory_id")
            scope = cand.get("scope") or "user"
            if decision in ("merge", "supersede") and target_id and target_id in approved_map:
                group_key = (scope, target_id)
                groups.setdefault(group_key, []).append(cand)

        created_consolidated_candidates = []
        today_str = datetime.now(JST).date().isoformat()
        timestamp_now = get_current_timestamp()

        for (scope, target_id), source_cands in groups.items():
            if len(source_cands) < 2:
                continue

            target_mem = approved_map[target_id]
            formatted_candidates = []
            for idx, c in enumerate(source_cands, 1):
                c_str = f"=== 候補 {idx} ===\n"
                c_str += f"- 候補ID: {c['memory_id']}\n"
                c_str += f"  判定キー(memory_key): {c.get('memory_key') or ''}\n"
                c_str += f"  種別: {c.get('kind') or ''}\n"
                c_str += f"  本文: {c.get('content') or ''}\n"
                c_str += f"  トピック: {c.get('topics') or []}\n"
                c_str += f"  タグ: {c.get('tags') or []}\n"
                c_str += f"  根拠: {json.dumps(c.get('evidence') or [], ensure_ascii=False)}\n"
                formatted_candidates.append(c_str)

            candidates_list_text = "\n".join(formatted_candidates)

            rendered_prompt = prompt.render_prompt(
                config.CANDIDATE_CONSOLIDATION_PROMPT_PATH,
                {
                    "target_id": target_id,
                    "target_memory_key": target_mem.get("memory_key") or "(なし)",
                    "target_kind": target_mem.get("kind") or "fact",
                    "target_content": target_mem.get("content") or "",
                    "candidates_list": candidates_list_text,
                },
            )

            try:
                response = llm_client.generate_llm_response(
                    provider=config.MEMORY_EXTRACTOR_PROVIDER,
                    model=config.MEMORY_EXTRACTOR_MODEL,
                    prompt=rendered_prompt,
                    max_tokens=16384,
                    temperature=0.2,
                ).strip()

                if response.startswith("```"):
                    lines = response.splitlines()
                    if len(lines) >= 2:
                        if lines[0].startswith("```json") or lines[0].startswith("```"):
                            response = "\n".join(lines[1:-1]).strip()

                llm_res = json.loads(response)
                if not isinstance(llm_res, dict):
                    raise ValueError("LLM response is not a JSON object")

                decision = llm_res.get("decision")
                if decision not in ("merge", "supersede", "new"):
                    raise ValueError(f"Invalid decision '{decision}' in LLM response")

                if decision in ("merge", "supersede"):
                    res_target_id = llm_res.get("target_memory_id")
                    if res_target_id != target_id:
                        raise ValueError(
                            f"target_memory_id mismatch: expected '{target_id}', got '{res_target_id}'"
                        )

                if decision == "merge":
                    integrated_content = llm_res.get("integrated_content")
                    if not isinstance(integrated_content, str) or not integrated_content.strip():
                        raise ValueError("decision is 'merge' but integrated_content is missing/empty")

                content = (
                    llm_res.get("integrated_content") if decision == "merge" else llm_res.get("content")
                )
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Consolidated content is missing or empty")

            except Exception as exc:
                logger.warning(
                    "Candidate consolidation LLM or validation failed for target %s (scope: %s): %s",
                    target_id,
                    scope,
                    exc,
                )
                continue

            # Validation succeeded. Construct consolidated candidate
            from obsidian_ai_hub.memory.agent_tools import (
                ALLOWED_KINDS,
                _normalize_memory_key,
            )

            raw_kind = llm_res.get("kind") or source_cands[0].get("kind") or "fact"
            validated_kind = raw_kind if isinstance(raw_kind, str) and raw_kind in ALLOWED_KINDS else "fact"
            if validated_kind != raw_kind:
                logger.warning(
                    "Invalid kind %r for target %s; coercing to 'fact'",
                    raw_kind,
                    target_id,
                )
            try:
                validated_memory_key = _normalize_memory_key(llm_res.get("memory_key") or "")
            except ValueError as exc:
                logger.warning(
                    "Candidate consolidation memory_key validation failed for target %s (scope: %s): %s",
                    target_id,
                    scope,
                    exc,
                )
                continue

            new_memory_id = generate_memory_id(today_str)
            target_fp = (
                compute_memory_fingerprint(target_mem) if decision in ("merge", "supersede") else None
            )

            combined_evidence = _deduplicate_evidence([c.get("evidence") or [] for c in source_cands])
            combined_topics = _deduplicate_topics(
                [c.get("topics") or [] for c in source_cands] + [llm_res.get("topics") or []]
            )
            combined_tags = _deduplicate_tags(
                [c.get("tags") or [] for c in source_cands] + [llm_res.get("tags") or []]
            )
            combined_contradicts = _deduplicate_contradicts(
                [c.get("contradicts") or [] for c in source_cands]
            )

            # Combine people for person scope
            combined_people = []
            if scope == "person":
                seen_pids = set()
                for c in source_cands:
                    for p in c.get("people") or []:
                        pid = p.get("person_id") if isinstance(p, dict) else str(p)
                        if pid and pid not in seen_pids:
                            seen_pids.add(pid)
                            combined_people.append(p)

            consolidated_cand = {
                "schema_version": 1,
                "memory_id": new_memory_id,
                "status": "candidate",
                "scope": scope,
                "kind": validated_kind,
                "memory_key": validated_memory_key,
                "content": content.strip(),
                "topics": combined_topics,
                "tags": combined_tags,
                "evidence": combined_evidence,
                "valid_from": _get_min_valid_from(source_cands) or today_str,
                "valid_until": None,
                "review_due_at": None,
                "stability": source_cands[0].get("stability", "tentative"),
                "sensitivity": source_cands[0].get("sensitivity", "personal"),
                "extraction_confidence": _get_max_confidence(source_cands),
                "supersedes": None,
                "contradicts": combined_contradicts,
                "provenance": {
                    "extraction_method": "candidate_consolidation",
                    "prompt_version": "candidate-consolidation-v1",
                    "model": f"{config.MEMORY_EXTRACTOR_PROVIDER}:{config.MEMORY_EXTRACTOR_MODEL}",
                    "consolidation": {
                        "source_candidate_ids": [c["memory_id"] for c in source_cands],
                        "target_memory_id": target_id if decision in ("merge", "supersede") else None,
                    },
                },
                "created_at": timestamp_now,
                "updated_at": timestamp_now,
                "reviewed_by": None,
                "reviewed_at": None,
                "dedup_suggestions": [
                    {
                        "target_memory_id": target_id,
                        "relation": decision,
                        "reason": llm_res.get("reason") or "同一メモリ向けの候補統合判定",
                        "score": 1.0,
                    }
                ]
                if decision in ("merge", "supersede")
                else None,
                "dedup_assessment": {
                    "decision": decision,
                    "target_memory_id": target_id if decision in ("merge", "supersede") else None,
                    "target_fingerprint": target_fp,
                    "similarity_score": 1.0,
                    "reason": llm_res.get("reason") or "同一メモリ向けの候補統合判定",
                },
                "people": combined_people,
            }
            if decision == "merge":
                consolidated_cand["dedup_assessment"]["integrated_content"] = llm_res.get("integrated_content")

            # Save consolidated candidate & transition source candidates in single transaction
            try:
                with conn:
                    db_row = serialize_memory(consolidated_cand)
                    columns = ", ".join(MEMORY_COLUMNS)
                    placeholders = ", ".join("?" for _ in MEMORY_COLUMNS)
                    conn.execute(
                        f"INSERT INTO memories ({columns}) VALUES ({placeholders})",
                        tuple(db_row.get(col) for col in MEMORY_COLUMNS),
                    )
                    if scope == "person":
                        for p in combined_people:
                            pid = p["person_id"] if isinstance(p, dict) else str(p)
                            conn.execute(
                                "INSERT INTO memory_people (memory_id, person_id, created_at) VALUES (?, ?, ?)",
                                (new_memory_id, pid, timestamp_now),
                            )

                    log_memory_event(
                        event_type="created",
                        memory_id=new_memory_id,
                        previous_status=None,
                        new_status="candidate",
                        conn=conn,
                        actor="system",
                    )

                    for src in source_cands:
                        cursor = conn.execute(
                            "UPDATE memories SET status = 'rejected', reviewed_by = 'system', reviewed_at = ?, updated_at = ? WHERE memory_id = ? AND status = 'candidate'",
                            (timestamp_now, timestamp_now, src["memory_id"]),
                        )
                        if cursor.rowcount == 0:
                            raise ValueError(
                                f"source candidate {src['memory_id']} is no longer 'candidate'"
                            )
                        log_memory_event(
                            event_type="consolidated",
                            memory_id=src["memory_id"],
                            previous_status="candidate",
                            new_status="rejected",
                            actor="system",
                            changes={
                                "consolidated_into_memory_id": new_memory_id,
                                "target_memory_id": target_id,
                            },
                            reason="同一メモリ向けの統合候補へ再構成されたためシステム自動却下",
                            conn=conn,
                        )
            except Exception as exc:
                logger.warning(
                    "Candidate consolidation DB transaction failed for target %s (scope: %s): %s",
                    target_id,
                    scope,
                    exc,
                )
                continue

            created_consolidated_candidates.append(consolidated_cand)

        return created_consolidated_candidates
    finally:
        if close_conn and conn is not None:
            conn.close()
