from __future__ import annotations

import json
import logging

from obsidian_ai_hub.utils import config, prompt

from obsidian_ai_hub.memory.models import (
    estimate_tokens,
    normalize_content,
)

logger = logging.getLogger(__name__)


def run_deduplication(
    candidate: dict, existing_memories: list[dict], embedder=None
) -> list[dict]:
    from obsidian_ai_hub.utils.embeddings import cosine_similarity

    suggestions = []
    cand_norm = normalize_content(candidate.get("content", ""))
    cand_key = candidate.get("memory_key", "")

    # We only dedup against currently active approved memories
    approved_mems = [m for m in existing_memories if m.get("status") == "approved"]
    if not approved_mems:
        return suggestions

    candidate_vector = None
    if embedder is not None and cand_norm:
        try:
            candidate_vector = embedder.embed_query(cand_norm)
        except Exception as e:
            logger.warning(f"Failed to generate embedding for candidate: {e}")

    for existing in approved_mems:
        ex_norm = normalize_content(existing.get("content", ""))
        ex_key = existing.get("memory_key", "")
        ex_id = existing.get("memory_id", "")

        # 1. memory_key exact match
        if cand_key and cand_key == ex_key:
            if cand_norm == ex_norm:
                suggestions.append(
                    {
                        "target_memory_id": ex_id,
                        "relation": "duplicate",
                        "reason": "同じmemory_keyで内容が実質的に一致する",
                        "score": 1.0,
                    }
                )
            else:
                suggestions.append(
                    {
                        "target_memory_id": ex_id,
                        "relation": "supersedes",
                        "reason": "同じmemory_keyで内容が更新されているため置換を提案",
                        "score": 1.0,
                    }
                )
            continue

        # 2. Normalized content match
        if cand_norm and cand_norm == ex_norm:
            suggestions.append(
                {
                    "target_memory_id": ex_id,
                    "relation": "duplicate",
                    "reason": "内容が既存の記憶と完全に一致する",
                    "score": 1.0,
                }
            )
            continue

        # 3. Vector similarity
        if candidate_vector is not None and ex_norm:
            try:
                ex_vector = embedder.embed_query(ex_norm)
                sim = cosine_similarity(candidate_vector, ex_vector)
                if sim >= 0.85:
                    suggestions.append(
                        {
                            "target_memory_id": ex_id,
                            "relation": "duplicate",
                            "reason": "既存の記憶と非常に内容が類似している",
                            "score": round(sim, 2),
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to compute similarity with {ex_id}: {e}")

    return suggestions


DEDUP_INPUT_BATCH_TOKEN_LIMIT = 24000
DEDUP_LLM_OUTPUT_TOKEN_LIMIT = 24000


def perform_dedup_assessment_llm(
    candidates_to_assess: list[dict], existing_memories: list[dict]
) -> None:
    if not candidates_to_assess:
        return

    # Find approved memories mapped by memory_id for quick lookup
    approved_map = {
        m["memory_id"]: m for m in existing_memories if m.get("status") == "approved"
    }

    # Build comparison groups
    comparison_groups = []
    for cand in candidates_to_assess:
        targets_info = []
        target_ids = []
        for sug in cand.get("dedup_suggestions", []):
            tid = sug.get("target_memory_id")
            target_mem = approved_map.get(tid)
            if target_mem:
                targets_info.append(
                    {
                        "memory_id": tid,
                        "memory_key": target_mem.get("memory_key") or "",
                        "content": target_mem.get("content") or "",
                        "relation": sug.get("relation") or "",
                        "score": sug.get("score"),
                    }
                )
                target_ids.append(tid)

        if targets_info:
            comparison_groups.append(
                {"candidate": cand, "targets": targets_info, "target_ids": target_ids}
            )

    if not comparison_groups:
        return

    # Batching based on token estimation
    batches = []
    current_batch = []
    current_tokens = 0

    # Let's estimate tokens of a simple empty template
    try:
        empty_prompt = prompt.render_prompt(
            config.BASE_DIR / "config" / "prompts" / "memory_dedup_review.md",
            {"comparison_list": ""},
        )
    except Exception:
        # Fallback if config files are not in expected places during tests
        empty_prompt = "Compare candidate memories"
    base_tokens = estimate_tokens(empty_prompt)

    def format_group_text(grp, idx):
        c = grp["candidate"]
        text = f"=== 比較グループ {idx} ===\n"
        text += "【新しく抽出された候補（Candidate）】\n"
        text += f"- 候補ID: {c['memory_id']}\n"
        text += f"- 判定キー(memory_key): {c.get('memory_key') or ''}\n"
        text += f"- 本文: {c.get('content') or ''}\n\n"
        text += "【既存の承認済み記憶（Target）】\n"
        for t in grp["targets"]:
            text += f"- 既存記憶ID: {t['memory_id']}\n"
            text += f"  判定キー(memory_key): {t['memory_key']}\n"
            text += f"  本文: {t['content']}\n"
            text += f"  類似関係: {t['relation']} (類似度: {t['score'] or '1.0'})\n"
        text += "\n"
        return text

    for i, grp in enumerate(comparison_groups, 1):
        grp_text = format_group_text(grp, i)
        grp_tokens = estimate_tokens(grp_text)
        if base_tokens + current_tokens + grp_tokens > DEDUP_INPUT_BATCH_TOKEN_LIMIT:
            if current_batch:
                batches.append(current_batch)
                current_batch = [grp]
                current_tokens = grp_tokens
            else:
                batches.append([grp])
                current_batch = []
                current_tokens = 0
        else:
            current_batch.append(grp)
            current_tokens += grp_tokens

    if current_batch:
        batches.append(current_batch)

    # Process each batch
    for batch in batches:
        comp_text = ""
        for idx, grp in enumerate(batch, 1):
            comp_text += format_group_text(grp, idx)

        prompt_path = config.BASE_DIR / "config" / "prompts" / "memory_dedup_review.md"
        try:
            rendered_prompt = prompt.render_prompt(
                prompt_path, {"comparison_list": comp_text}
            )
        except Exception:
            rendered_prompt = f"Please review these and return JSON:\n{comp_text}"

        try:
            from obsidian_ai_hub import memory as _memory_facade

            response = _memory_facade.llm_client.generate_llm_response(
                provider=config.MEMORY_EXTRACTOR_PROVIDER,
                model=config.MEMORY_EXTRACTOR_MODEL,
                prompt=rendered_prompt,
                max_tokens=DEDUP_LLM_OUTPUT_TOKEN_LIMIT,
                temperature=0.2,
            ).strip()

            if response.startswith("```"):
                lines = response.splitlines()
                if len(lines) >= 2:
                    if lines[0].startswith("```json") or lines[0].startswith("```"):
                        response = "\n".join(lines[1:-1]).strip()

            try:
                results = json.loads(response)
                if not isinstance(results, list):
                    results = [results]
            except json.JSONDecodeError as je:
                logger.error(
                    f"Failed to parse LLM response as JSON. Error: {je}. Response: {response}"
                )
                raise ValueError("response_invalid")

            results_by_cand = {}
            for r in results:
                if isinstance(r, dict) and "candidate_id" in r:
                    results_by_cand[r["candidate_id"]] = r

            for grp in batch:
                c = grp["candidate"]
                cid = c["memory_id"]
                res_item = results_by_cand.get(cid)

                valid = False
                if res_item:
                    decision = res_item.get("decision")
                    target_id = res_item.get("target_memory_id")
                    integrated_content = res_item.get("integrated_content")
                    reason = res_item.get("reason") or "LLM判定"

                    if decision in ("merge", "supersede", "new"):
                        if decision in ("merge", "supersede"):
                            if target_id in grp["target_ids"]:
                                if decision == "merge":
                                    if (
                                        isinstance(integrated_content, str)
                                        and integrated_content.strip()
                                    ):
                                        valid = True
                                else:
                                    valid = True
                        else:
                            valid = True

                if valid:
                    score = 1.0
                    for t in grp["targets"]:
                        if t["memory_id"] == target_id:
                            score = t["score"] if t["score"] is not None else 1.0
                            break

                    assessment = {
                        "decision": decision,
                        "target_memory_id": target_id
                        if decision in ("merge", "supersede")
                        else None,
                        "similarity_score": score,
                        "reason": reason,
                    }
                    if decision == "merge":
                        assessment["integrated_content"] = integrated_content

                    c["dedup_assessment"] = assessment
                else:
                    logger.warning(
                        f"Invalid or missing LLM response item for candidate {cid}: {res_item}"
                    )
                    scores = [
                        t["score"] for t in grp["targets"] if t["score"] is not None
                    ]
                    best_score = max(scores) if scores else 1.0
                    c["dedup_assessment"] = {
                        "decision": "failed",
                        "similarity_score": best_score,
                        "reason": "LLM response was invalid or failed validation checks",
                        "failure_kind": "response_invalid",
                    }

        except Exception as exc:
            logger.exception(f"LLM request or parsing failed for batch: {exc}")
            failure_kind = (
                "response_invalid"
                if str(exc) == "response_invalid"
                else "request_failed"
            )
            for grp in batch:
                c = grp["candidate"]
                scores = [t["score"] for t in grp["targets"] if t["score"] is not None]
                best_score = max(scores) if scores else 1.0
                c["dedup_assessment"] = {
                    "decision": "failed",
                    "similarity_score": best_score,
                    "reason": f"Failed to get or parse LLM response: {str(exc)}",
                    "failure_kind": failure_kind,
                }
