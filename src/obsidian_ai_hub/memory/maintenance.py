from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import sqlite3

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils import config, llm_client, prompt
from obsidian_ai_hub.memory.models import (
    deserialize_memory,
    serialize_memory,
    get_current_timestamp,
    normalize_content,
    MEMORY_COLUMNS,
)
from obsidian_ai_hub.memory.store import log_memory_event, load_all_memories
from obsidian_ai_hub.memory.projection import project_approved_memories
from obsidian_ai_hub.hitl.service import register_run_and_questions
from obsidian_ai_hub.hitl.dispatcher import HitlResult, HitlContext
from obsidian_ai_hub.utils.embeddings import cosine_similarity, get_embedder

logger = logging.getLogger(__name__)


def parse_jst_date(date_str: str) -> Optional[datetime]:
    """Parse YYYY-MM-DD or ISO 8601 string, normalizing to JST date."""
    if not date_str:
        return None
    try:
        # ISO 8601
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str)
            # Convert to JST (UTC+9)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone(timedelta(hours=9)))
            else:
                dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            # YYYY-MM-DD
            dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
            return dt.replace(tzinfo=timezone(timedelta(hours=9)))
    except Exception:
        return None


def is_obsolete(m: dict, base_date: datetime) -> bool:
    """
    Check if memory is obsolete/expired.
    - valid_until or review_due_at is expired (strictly before base_date).
    - latest observed_at in evidence is >= 180 days before base_date.
    """
    # 1. Check valid_until expiration (strictly before base_date)
    valid_until = m.get("valid_until")
    if valid_until:
        vu_dt = parse_jst_date(valid_until)
        if vu_dt and vu_dt < base_date:
            return True

    # 2. Check review_due_at expiration (strictly before base_date)
    review_due_at = m.get("review_due_at")
    if review_due_at:
        rd_dt = parse_jst_date(review_due_at)
        if rd_dt and rd_dt < base_date:
            return True

    # 3. Check evidence observed_at (observed_at >= 180 days ago)
    evidence_list = m.get("evidence") or []
    latest_observed: Optional[datetime] = None
    for ev in evidence_list:
        observed_at = ev.get("observed_at")
        if observed_at:
            obs_dt = parse_jst_date(observed_at)
            if obs_dt:
                if latest_observed is None or obs_dt > latest_observed:
                    latest_observed = obs_dt

    if latest_observed:
        days_diff = (base_date - latest_observed).days
        if days_diff >= 180:
            return True

    return False


def build_maintenance_groups(memories: List[Dict[str, Any]], embedder=None) -> List[List[Dict[str, Any]]]:
    """
    Group approved memories by memory_key, exact normalized content, or vector similarity >= 0.85.
    Returns a list of disjoint memory groups.
    """
    approved_mems = [m for m in memories if m.get("status") == "approved"]
    if not approved_mems:
        return []

    # Map each memory to an index
    id_to_idx = {m["memory_id"]: i for i, m in enumerate(approved_mems)}
    n = len(approved_mems)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    # Generate content representations & vector embeddings if embedder is available
    norms = [normalize_content(m.get("content", "")) for m in approved_mems]
    keys = [m.get("memory_key") for m in approved_mems]

    vectors = [None] * n
    if embedder is not None:
        for i, norm in enumerate(norms):
            if norm:
                try:
                    vectors[i] = embedder.embed_query(norm)
                except Exception as e:
                    logger.warning(f"Failed to embed memory content: {e}")

    # Pairwise comparison
    for i in range(n):
        for j in range(i + 1, n):
            # 1. Same memory key
            if keys[i] and keys[i] == keys[j]:
                union(i, j)
                continue

            # 2. Exact content normalized match
            if norms[i] and norms[i] == norms[j]:
                union(i, j)
                continue

            # 3. Embedding similarity >= 0.85
            if vectors[i] is not None and vectors[j] is not None:
                sim = cosine_similarity(vectors[i], vectors[j])
                if sim >= 0.85:
                    union(i, j)

    # Collect groups
    groups_map: Dict[int, List[Dict[str, Any]]] = {}
    for i in range(n):
        root = find(i)
        if root not in groups_map:
            groups_map[root] = []
        groups_map[root].append(approved_mems[i])

    return list(groups_map.values())


def render_memory_record(m: dict) -> str:
    """Format memory fields for LLM prompt ingestion."""
    lines = [
        f"- ID: {m.get('memory_id')}",
        f"  Key: {m.get('memory_key') or '(none)'}",
        f"  Content: {m.get('content')}",
        f"  Topics: {m.get('topics') or '[]'}",
        f"  Tags: {m.get('tags') or '[]'}",
        f"  Evidence: {json.dumps(m.get('evidence') or [], ensure_ascii=False)}",
        f"  Valid From: {m.get('valid_from') or '(none)'}",
        f"  Valid Until: {m.get('valid_until') or '(none)'}",
        f"  Review Due At: {m.get('review_due_at') or '(none)'}",
        f"  Stability: {m.get('stability') or '(none)'}",
        f"  Created At: {m.get('created_at') or '(none)'}",
        f"  Updated_at: {m.get('updated_at') or '(none)'}",
    ]
    return "\n".join(lines)


def validate_proposals(proposals: List[Dict[str, Any]], target_mem_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Validate LLM structured proposals:
    - Must be a list of dicts.
    - All IDs in `main_id` and `absorbed_ids` must exist in target_mem_ids.
    - IDs must not overlap within a single proposal.
    - Across all proposals, no ID can be processed more than once.
    - Must have essential fields (reason, integrated_content, etc.).
    """
    valid_proposals = []
    processed_ids = set()
    target_set = set(target_mem_ids)

    for p in proposals:
        if not isinstance(p, dict):
            continue
        action = p.get("action")
        if action not in ("merge", "correct", "expire", "no_action"):
            continue
        if action == "no_action":
            continue

        main_id = p.get("main_id")
        absorbed_ids = p.get("absorbed_ids") or []

        if not main_id or main_id not in target_set:
            continue
        if any(aid not in target_set for aid in absorbed_ids):
            continue

        # Overlap within proposal
        if main_id in absorbed_ids or len(set(absorbed_ids)) != len(absorbed_ids):
            continue

        # Overlap across proposals
        if main_id in processed_ids or any(aid in processed_ids for aid in absorbed_ids):
            continue

        # merge / correct requires integrated_content and non-empty absorbed_ids
        if action in ("merge", "correct"):
            if not p.get("integrated_content") or not p.get("integrated_content").strip():
                continue
            if not absorbed_ids:
                continue

        # Valid proposal! Add to result
        valid_proposals.append({
            "action": action,
            "main_id": main_id,
            "absorbed_ids": list(absorbed_ids),
            "reason": p.get("reason") or "LLM診断提案",
            "integrated_content": p.get("integrated_content") if action in ("merge", "correct") else None,
        })

        processed_ids.add(main_id)
        for aid in absorbed_ids:
            processed_ids.add(aid)

    return valid_proposals


def run_maintenance_diagnosis(
    base_date: datetime,
    memories: List[Dict[str, Any]],
    embedder=None,
) -> List[Dict[str, Any]]:
    """
    Perform maintenance diagnosis using LLM and vector groupings.
    Checks obsolete memories and similar groups, returning compiled maintenance proposals.
    """
    # 1. Build similar groups
    groups = build_maintenance_groups(memories, embedder=embedder)

    # 2. Check independent obsolete memories
    grouped_ids = {m["memory_id"] for g in groups for m in g}
    obsolete_independent = []
    for m in memories:
        if m.get("status") == "approved" and m["memory_id"] not in grouped_ids:
            if is_obsolete(m, base_date):
                obsolete_independent.append([m])

    # Combine all candidate groupings for LLM review
    all_candidate_groups = groups + obsolete_independent
    all_proposals = []

    for grp in all_candidate_groups:
        # If group only has 1 memory and it's NOT obsolete, we don't need maintenance diagnosis
        if len(grp) == 1 and not is_obsolete(grp[0], base_date):
            continue

        # Invoke LLM for maintenance assessment
        target_texts = [render_memory_record(m) for m in grp]
        target_memories_text = "\n\n".join(target_texts)
        target_ids = [m["memory_id"] for m in grp]

        rendered_prompt = prompt.render_prompt(
            config.BASE_DIR / "config" / "prompts" / "memory_maintenance.md",
            {
                "input_mode": "diagnose",
                "target_memories_text": target_memories_text,
                "base_date": base_date.strftime("%Y-%m-%d"),
                "original_proposal_text": "",
                "user_comment_text": "",
            },
        )

        try:
            response = llm_client.generate_llm_response(
                provider=config.MEMORY_EXTRACTOR_PROVIDER,
                model=config.MEMORY_EXTRACTOR_MODEL,
                prompt=rendered_prompt,
                temperature=0.2,
                max_tokens=8000,
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
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse LLM response as JSON: {response}")
                continue

            # Validate proposals against the exact group memories
            group_proposals = validate_proposals(results, target_ids)
            all_proposals.extend(group_proposals)

        except Exception as e:
            logger.exception(f"Failed to perform LLM memory maintenance diagnosis: {e}")

    return all_proposals


def register_maintenance_hitl_run(
    base_date: datetime,
    proposals: List[Dict[str, Any]],
    memories_map: Dict[str, dict],
) -> Optional[str]:
    """
    Register a new maintenance run with HitlQuestions representing proposals.
    """
    if not proposals:
        return None

    run_id = f"mem_maint_{int(base_date.timestamp())}"
    question_set_id = "round_1"

    questions_data = []
    for i, p in enumerate(proposals, 1):
        q_key = f"proposal_{i}"

        main_mem = memories_map.get(p["main_id"])
        absorbed_mems = [memories_map[aid] for aid in p["absorbed_ids"] if aid in memories_map]

        display_text = f"【{p['action'].upper()} 提案】正本ID: {p['main_id']}"
        if p["absorbed_ids"]:
            display_text += f"、吸収ID: {', '.join(p['absorbed_ids'])}"

        # Structure context_json neatly for frontend rendering
        context_json = {
            "type": "memory_maintenance",
            "proposal_id": q_key,
            "action": p["action"],
            "main_id": p["main_id"],
            "absorbed_ids": p["absorbed_ids"],
            "reason": p["reason"],
            "integrated_content": p["integrated_content"],
            "target_memories": [main_mem] + absorbed_mems,
        }

        questions_data.append({
            "question_key": q_key,
            "question_type": "select",
            "display_text": display_text,
            "choices": [
                {"value": "apply", "label": "適用", "description": "提案内容をデータベースに適用します。"},
                {"value": "skip", "label": "見送り", "description": "今回の提案は見送ります（変更は加えません）。"},
                {"value": "feedback", "label": "フィードバックして再提案", "description": "コメント付きで再診断を要求します。"},
            ],
            "is_required": 1,
            "sequence": i,
            "title": f"提案 #{i}",
            "prompt": p["reason"],
            "context_json": context_json,
        })

    # Prepare checkpoint snapshot mapping ID -> updated_at
    snapshots = {}
    for p in proposals:
        for mid in [p["main_id"]] + p["absorbed_ids"]:
            if mid in memories_map:
                snapshots[mid] = memories_map[mid].get("updated_at")

    checkpoint = json.dumps({
        "base_date": base_date.strftime("%Y-%m-%d"),
        "proposals": proposals,
        "proposal_round": 1,
        "snapshots": snapshots,
        "applied_proposal_ids": [],
    })

    register_run_and_questions(
        run_id=run_id,
        handler="memory.apply_maintenance_proposals",
        checkpoint=checkpoint,
        question_set_id=question_set_id,
        questions_data=questions_data,
        title="メモリ長期記憶 診断メンテナンス",
        description=f"基準日 {base_date.strftime('%Y-%m-%d')} の長期記憶定期診断に基づく、{len(proposals)}件のメンテナンス提案です。",
        display_type="長期記憶保守",
    )

    return run_id


def check_snapshot_conflicts(p: dict, expected_snapshots: dict, current_memories_map: dict) -> bool:
    """Return True if any of the target memories have been modified from their snapshot state."""
    target_ids = [p["main_id"]] + p.get("absorbed_ids", [])
    for mid in target_ids:
        expected = expected_snapshots.get(mid)
        current_m = current_memories_map.get(mid)
        if not current_m:
            return True
        if current_m.get("updated_at") != expected:
            return True
    return False


def apply_single_proposal(
    conn: sqlite3.Connection,
    p: dict,
    proposal_id: str,
    memories_map: dict,
) -> None:
    """Execute merge, correct, or expire on the SQLite DB in a safe transaction."""
    action = p["action"]
    main_id = p["main_id"]
    absorbed_ids = p.get("absorbed_ids", [])
    integrated_content = p.get("integrated_content")
    reason = p["reason"]
    timestamp_now = get_current_timestamp()

    if action in ("merge", "correct"):
        main_mem = memories_map[main_id]
        before_content = main_mem.get("content", "")

        # 1. Update main record with integrated content
        # Also inherit topics, tags, and evidence from absorbed records
        merged_topics = list(main_mem.get("topics") or [])
        merged_tags = list(main_mem.get("tags") or [])
        merged_evidence = list(main_mem.get("evidence") or [])

        for aid in absorbed_ids:
            if aid in memories_map:
                amem = memories_map[aid]
                for t in amem.get("topics") or []:
                    if t not in merged_topics:
                        merged_topics.append(t)
                for tg in amem.get("tags") or []:
                    if tg not in merged_tags:
                        merged_tags.append(tg)
                for ev in amem.get("evidence") or []:
                    if ev not in merged_evidence:
                        merged_evidence.append(ev)

        main_mem["content"] = integrated_content
        main_mem["topics"] = merged_topics
        main_mem["tags"] = merged_tags
        main_mem["evidence"] = merged_evidence
        main_mem["updated_at"] = timestamp_now

        db_row = serialize_memory(main_mem)
        set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
        conn.execute(
            f"UPDATE memories SET {set_clause} WHERE memory_id = ?",
            [db_row.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [main_id]
        )

        # Log main record event
        event_type = "maintenance_merged" if action == "merge" else "maintenance_corrected"
        changes = {
            "content": {"before": before_content, "after": integrated_content},
            "absorbed_ids": absorbed_ids,
            "proposal_id": proposal_id,
        }
        log_memory_event(
            event_type=event_type,
            memory_id=main_id,
            previous_status="approved",
            new_status="approved",
            changes=changes,
            reason=reason,
            conn=conn,
            actor="system",
        )

        # 2. Set absorbed records to superseded
        for aid in absorbed_ids:
            if aid in memories_map:
                amem = memories_map[aid]
                prev_status = amem.get("status")
                amem["status"] = "superseded"
                amem["updated_at"] = timestamp_now

                db_row_abs = serialize_memory(amem)
                conn.execute(
                    "UPDATE memories SET status = ?, updated_at = ? WHERE memory_id = ?",
                    ("superseded", timestamp_now, aid)
                )

                log_memory_event(
                    event_type="maintenance_superseded",
                    memory_id=aid,
                    previous_status=prev_status,
                    new_status="superseded",
                    changes={
                        "action": action,
                        "main_id": main_id,
                        "proposal_id": proposal_id,
                    },
                    reason=f"マージ統合/矛盾訂正により正本ID:{main_id}へ吸収。提案ID:{proposal_id}",
                    conn=conn,
                    actor="system",
                )

    elif action == "expire":
        main_mem = memories_map[main_id]
        prev_status = main_mem.get("status")
        main_mem["status"] = "expired"
        main_mem["updated_at"] = timestamp_now

        conn.execute(
            "UPDATE memories SET status = ?, updated_at = ? WHERE memory_id = ?",
            ("expired", timestamp_now, main_id)
        )

        log_memory_event(
            event_type="expired",
            memory_id=main_id,
            previous_status=prev_status,
            new_status="expired",
            changes={"proposal_id": proposal_id},
            reason=reason,
            conn=conn,
            actor="system",
        )


def re_diagnose_individual_proposal(
    p: dict,
    base_date: str,
    current_memories_map: dict,
    user_comment: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Rerun LLM diagnosis on a specific proposal's subset of memories.
    Provides comment if returning from 'feedback'.
    """
    target_ids = [p["main_id"]] + p.get("absorbed_ids", [])
    mems = [current_memories_map[mid] for mid in target_ids if mid in current_memories_map]
    if not mems:
        return []

    target_texts = [render_memory_record(m) for m in mems]
    target_memories_text = "\n\n".join(target_texts)

    if user_comment:
        input_mode = "feedback"
        original_proposal_text = json.dumps(p, ensure_ascii=False, indent=2)
    else:
        input_mode = "conflict_re_diagnose"
        original_proposal_text = ""

    rendered_prompt = prompt.render_prompt(
        config.BASE_DIR / "config" / "prompts" / "memory_maintenance.md",
        {
            "input_mode": input_mode,
            "target_memories_text": target_memories_text,
            "base_date": base_date,
            "original_proposal_text": original_proposal_text,
            "user_comment_text": user_comment or "",
        },
    )

    try:
        response = llm_client.generate_llm_response(
            provider=config.MEMORY_EXTRACTOR_PROVIDER,
            model=config.MEMORY_EXTRACTOR_MODEL,
            prompt=rendered_prompt,
            temperature=0.2,
            max_tokens=8000,
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
        except json.JSONDecodeError:
            return []

        return validate_proposals(results, target_ids)
    except Exception as e:
        logger.exception(f"Individual re-diagnosis failed: {e}")
        return []


def run_approved_maintenance(ctx: HitlContext) -> HitlResult:
    """
    Handler to apply and transition maintenance proposals.
    Executes on dispatcher trigger once the user answers.
    """
    import json
    from obsidian_ai_hub.hitl.service import update_checkpoint

    checkpoint_data = json.loads(ctx.checkpoint)
    base_date_str = checkpoint_data["base_date"]
    proposals = checkpoint_data["proposals"]
    proposal_round = checkpoint_data["proposal_round"]
    expected_snapshots = checkpoint_data["snapshots"]
    applied_proposal_ids = checkpoint_data.get("applied_proposal_ids") or []

    # Reload all current memories to get latest states
    current_mems = load_all_memories()
    current_memories_map = {m["memory_id"]: m for m in current_mems}

    new_round_proposals = []
    has_conflicts = False

    # First pass: Verify snapshots and apply accepted non-conflicting proposals
    for idx, p in enumerate(proposals, 1):
        q_key = f"proposal_{idx}"
        user_choice = ctx.answers_by_question_key.get(q_key)

        # If already applied or skipped in a previous pass, skip
        if q_key in applied_proposal_ids:
            continue

        if user_choice == "apply":
            # Verify snapshot conflict
            conflict = check_snapshot_conflicts(p, expected_snapshots, current_memories_map)
            if conflict:
                has_conflicts = True
                # Trigger individual re-diagnosis right away
                re_diagnosed = re_diagnose_individual_proposal(p, base_date_str, current_memories_map)
                new_round_proposals.extend(re_diagnosed)
            else:
                # Safe to apply! Put inside an isolated commit
                try:
                    with ctx.conn:
                        apply_single_proposal(ctx.conn, p, q_key, current_memories_map)
                    applied_proposal_ids.append(q_key)
                except Exception as ex:
                    logger.exception(f"Failed to apply proposal {q_key}: {ex}")
                    return HitlResult.fail(f"Proposal application failed: {str(ex)}")

        elif user_choice == "feedback":
            user_comment = ""
            raw_ans = ctx.raw_answers_by_question_key.get(q_key)
            if isinstance(raw_ans, dict):
                user_comment = raw_ans.get("comment") or ""

            if not user_comment.strip():
                return HitlResult.fail(f"コメントが入力されていません。フィードバックして再提案にはコメントが必須です。")

            # Re-diagnose with feedback context
            re_diagnosed = re_diagnose_individual_proposal(p, base_date_str, current_memories_map, user_comment)
            new_round_proposals.extend(re_diagnosed)
            applied_proposal_ids.append(q_key)

        elif user_choice == "skip":
            # Just log skip in audit, no DB changes
            logger.info(f"Proposal {q_key} was skipped by user.")
            applied_proposal_ids.append(q_key)

    # Re-project approved memories markdown in case anything changed
    try:
        project_approved_memories()
    except Exception as proj_ex:
        logger.exception(f"Failed to project memories after maintenance: {proj_ex}")

    # Check if we have new proposals to present as the next set/round
    if new_round_proposals:
        next_round = proposal_round + 1
        next_question_set_id = f"round_{next_round}"

        questions_data = []
        for i, np in enumerate(new_round_proposals, 1):
            nq_key = f"proposal_{i}"
            main_mem = current_memories_map.get(np["main_id"])
            absorbed_mems = [current_memories_map[aid] for aid in np["absorbed_ids"] if aid in current_memories_map]

            display_text = f"【再提案 - {np['action'].upper()}】正本ID: {np['main_id']}"
            if np["absorbed_ids"]:
                display_text += f"、吸収ID: {', '.join(np['absorbed_ids'])}"

            context_json = {
                "type": "memory_maintenance",
                "proposal_id": nq_key,
                "action": np["action"],
                "main_id": np["main_id"],
                "absorbed_ids": np["absorbed_ids"],
                "reason": np["reason"],
                "integrated_content": np["integrated_content"],
                "target_memories": [main_mem] + absorbed_mems,
            }

            questions_data.append({
                "question_key": nq_key,
                "question_type": "select",
                "display_text": display_text,
                "choices": [
                    {"value": "apply", "label": "適用", "description": "提案内容をデータベースに適用します。"},
                    {"value": "skip", "label": "見送り", "description": "今回の提案は見送ります（変更は加えません）。"},
                    {"value": "feedback", "label": "フィードバックして再提案", "description": "コメント付きで再診断を要求します。"},
                ],
                "is_required": 1,
                "sequence": i,
                "title": f"再提案 #{i}",
                "prompt": np["reason"],
                "context_json": context_json,
            })

        # Update expected snapshots for the next round
        next_snapshots = {}
        for np in new_round_proposals:
            for mid in [np["main_id"]] + np["absorbed_ids"]:
                if mid in current_memories_map:
                    next_snapshots[mid] = current_memories_map[mid].get("updated_at")

        next_checkpoint = json.dumps({
            "base_date": base_date_str,
            "proposals": new_round_proposals,
            "proposal_round": next_round,
            "snapshots": next_snapshots,
            "applied_proposal_ids": [],
        })

        ctx.register_next_questions(
            question_set_id=next_question_set_id,
            questions_data=questions_data,
            checkpoint=next_checkpoint,
        )

        return HitlResult.re_suspend(checkpoint=next_checkpoint)

    # No more proposals left unresolved
    return HitlResult.complete(checkpoint=json.dumps({
        "base_date": base_date_str,
        "proposals": proposals,
        "proposal_round": proposal_round,
        "snapshots": expected_snapshots,
        "applied_proposal_ids": applied_proposal_ids,
        "finished": True,
    }))


def run_maintenance_cli() -> None:
    """Entry point for the `--memory-maintain` CLI command."""
    base_date = datetime.now(timezone(timedelta(hours=9)))
    print(f"[{base_date.strftime('%Y-%m-%d %H:%M:%S')}] 長期記憶の診断メンテナンスを開始します...")

    current_mems = load_all_memories()
    if not current_mems:
        print("承認済みの長期記憶が存在しません。診断をスキップします。")
        return

    embedder = get_embedder()
    proposals = run_maintenance_diagnosis(base_date, current_mems, embedder=embedder)

    if not proposals:
        print("保守診断の結果、新たに提案する改善項目はありませんでした。")
        return

    print(f"診断完了: {len(proposals)}件の改善提案が見つかりました。")
    for i, p in enumerate(proposals, 1):
        print(f"提案 #{i}: [{p['action'].upper()}] 正本ID: {p['main_id']}")
        print(f"  根拠: {p['reason']}")
        if p.get("integrated_content"):
            print(f"  統合本文: {p['integrated_content']}")

    memories_map = {m["memory_id"]: m for m in current_mems}
    run_id = register_maintenance_hitl_run(base_date, proposals, memories_map)
    if run_id:
        print(f"メンテナンス提案を HITL キューに登録しました。Run ID: {run_id}")
    else:
        print("HITL登録をスキップしました。")
