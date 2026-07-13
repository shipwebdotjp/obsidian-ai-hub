import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any, Optional, Sequence

from obsidian_ai_hub.utils import config, reader, extracter, llm_client, prompt
from obsidian_ai_hub.utils.topics import TOPIC_ENUM, normalize_topics

logger = logging.getLogger(__name__)

_embedder = None

def get_embedder():
    global _embedder
    if _embedder is not None:
        return _embedder
    try:
        from obsidian_ai_hub.utils.simple_sbert_embeddings import SimpleSbertEmbeddings
        _embedder = SimpleSbertEmbeddings(
            model_name=config.VAULT_INDEX_EMBEDDER_MODEL,
            allow_network_fallback=config.VAULT_INDEX_ALLOW_NETWORK_FALLBACK
        )
        return _embedder
    except Exception as e:
        logger.warning(f"SBERT Embeddings are not available: {e}. Vector search is disabled.")
        return None


def get_current_timestamp() -> str:
    # Use JST timezone for standard +09:00 formatting
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).isoformat(timespec="seconds")


def generate_memory_id(date_str: str) -> str:
    clean_date = date_str.replace("-", "")
    rand_part = uuid.uuid4().hex[:6]
    return f"mem_{clean_date}_{rand_part}"


def generate_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


def normalize_content(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r'\s+', '', text)
    return text


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = sum(a * a for a in v1) ** 0.5
    norm_b = sum(b * b for b in v2) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def get_memory_paths() -> tuple[Path, Path, Path]:
    vault_copilot = Path(config.VAULT_PATH) / "copilot"
    mem_dir = vault_copilot / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    return (
        mem_dir / "memories.jsonl",
        mem_dir / "memory_events.jsonl",
        mem_dir / "approved.md"
    )


def load_all_memories() -> list[dict]:
    mem_file, _, _ = get_memory_paths()
    memories = []
    if not mem_file.exists():
        return memories
    with open(mem_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                memories.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse memory line: {line}. Error: {e}")
    return memories


def save_all_memories(memories: list[dict]):
    import os
    mem_file, _, _ = get_memory_paths()
    # Write to a temporary file in the same directory to allow atomic replacement
    temp_file = mem_file.with_name(f"{mem_file.name}.tmp-{uuid.uuid4().hex}")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            for m in memories:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        # Atomically replace
        os.replace(temp_file, mem_file)
    except Exception as e:
        logger.error(f"Failed to save memories atomically: {e}")
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass
        raise


def log_memory_event(
    event_type: str,
    memory_id: str,
    previous_status: Optional[str],
    new_status: str,
    changes: Optional[dict] = None,
    reason: Optional[str] = None
):
    _, events_file, _ = get_memory_paths()
    event_record = {
        "schema_version": 1,
        "event_id": generate_event_id(),
        "occurred_at": get_current_timestamp(),
        "actor": "user",
        "event_type": event_type,
        "memory_id": memory_id,
        "previous_status": previous_status,
        "new_status": new_status,
        "changes": changes or {},
        "reason": reason
    }
    with open(events_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event_record, ensure_ascii=False) + "\n")


def project_approved_memories():
    _, _, approved_md_file = get_memory_paths()
    memories = load_all_memories()
    active_approved = [
        m for m in memories
        if m.get("status") == "approved"
    ]

    # Keep a fixed order of kinds
    kinds_order = ["preference", "decision_policy", "fact", "commitment", "pattern", "episode"]
    grouped_memories = {k: [] for k in kinds_order}
    for m in active_approved:
        kind = m.get("kind", "preference")
        if kind not in grouped_memories:
            grouped_memories[kind] = []
        grouped_memories[kind].append(m)

    lines = [
        "# Approved Memories",
        "",
        "> Generated from memories.jsonl. Do not edit manually.",
        ""
    ]

    for kind in kinds_order:
        m_list = grouped_memories[kind]
        if not m_list:
            continue
        lines.append(f"## {kind}")
        lines.append("")
        for m in m_list:
            lines.append(f"### {m['memory_id']}")
            lines.append("")
            lines.append(m.get("content", ""))
            lines.append("")
            lines.append(f"- Key: `{m.get('memory_key', '')}`")
            lines.append(f"- Stability: `{m.get('stability', 'stable')}`")
            evidence_lines = []
            for ev in m.get("evidence", []):
                path = ev.get("path", "")
                if path.endswith(".md"):
                    path = path[:-3]
                quote = ev.get("quote", "")
                evidence_lines.append(f"[[{path}]] — 「{quote}」")
            if evidence_lines:
                lines.append(f"- Evidence: {', '.join(evidence_lines)}")
            lines.append("")

    with open(approved_md_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).strip() + "\n")


def run_deduplication(candidate: dict, existing_memories: list[dict], embedder=None) -> list[dict]:
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
                suggestions.append({
                    "target_memory_id": ex_id,
                    "relation": "duplicate",
                    "reason": "同じmemory_keyで内容が実質的に一致する",
                    "score": 1.0
                })
            else:
                suggestions.append({
                    "target_memory_id": ex_id,
                    "relation": "supersedes",
                    "reason": "同じmemory_keyで内容が更新されているため置換を提案",
                    "score": 1.0
                })
            continue

        # 2. Normalized content match
        if cand_norm and cand_norm == ex_norm:
            suggestions.append({
                "target_memory_id": ex_id,
                "relation": "duplicate",
                "reason": "内容が既存の記憶と完全に一致する",
                "score": 1.0
            })
            continue

        # 3. Vector similarity
        if candidate_vector is not None and ex_norm:
            try:
                ex_vector = embedder.embed_query(ex_norm)
                sim = cosine_similarity(candidate_vector, ex_vector)
                if sim >= 0.85:
                    suggestions.append({
                        "target_memory_id": ex_id,
                        "relation": "duplicate",
                        "reason": "既存の記憶と非常に内容が類似している",
                        "score": round(sim, 2)
                    })
            except Exception as e:
                logger.warning(f"Failed to compute similarity with {ex_id}: {e}")

    return suggestions


def extract_memories(target_date_str: str) -> list[dict]:
    logger.info(f"Extracting memories for date: {target_date_str}")
    target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")

    # Load inputs
    # 1. Daily note content
    daily_content = reader.get_daily_note_content(target_dt)

    # 2. Daily structured record (from monthly jsonl)
    year_str = target_dt.strftime("%Y")
    month_str = target_dt.strftime("%m")
    monthly_jsonl_path = Path(config.ACTIVITY_PATH) / year_str / month_str / f"{year_str}-{month_str}.jsonl"

    structured_record = {}
    if monthly_jsonl_path.exists():
        with open(monthly_jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if data.get("date") == target_date_str:
                        structured_record = data
                        break
                except json.JSONDecodeError:
                    pass

    # 3. Structured activity log
    activity_logs = []
    from obsidian_ai_hub.summerize_day import load_activity_logs
    try:
        activity_logs = load_activity_logs(target_dt)
    except Exception as e:
        logger.warning(f"Failed to load activity logs: {e}")

    # Build and render prompt
    rendered_prompt = prompt.render_prompt(
        config.MEMORY_EXTRACTOR_PROMPT_PATH,
        {
            "target_date": target_date_str,
            "daily_note_content": daily_content or "(空)",
            "structured_record": json.dumps(structured_record, ensure_ascii=False, indent=2) if structured_record else "(なし)",
            "activity_logs": json.dumps(activity_logs, ensure_ascii=False, indent=2) if activity_logs else "(なし)",
            "topic_candidates": json.dumps(TOPIC_ENUM, ensure_ascii=False)
        }
    )

    # Call LLM
    response = llm_client.generate_llm_response(
        provider=config.MEMORY_EXTRACTOR_PROVIDER,
        model=config.MEMORY_EXTRACTOR_MODEL,
        prompt=rendered_prompt,
        max_tokens=32000,
        temperature=0.2
    ).strip()

    # Clean code blocks
    if response.startswith("```"):
        lines = response.splitlines()
        if len(lines) >= 2:
            if lines[0].startswith("```json") or lines[0].startswith("```"):
                response = "\n".join(lines[1:-1]).strip()

    candidates = []
    try:
        extracted = json.loads(response)
        if not isinstance(extracted, list):
            extracted = [extracted]
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM memory extraction response as JSON. Response: {response}. Error: {e}")
        return []

    existing_memories = load_all_memories()
    embedder = get_embedder()

    timestamp_now = get_current_timestamp()

    new_candidates = []
    for item in extracted:
        if not isinstance(item, dict):
            logger.warning(f"Skipping non-dict extracted candidate item: {item}")
            continue

        # Generate new ID
        memory_id = generate_memory_id(target_date_str)

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
            "valid_from": item.get("valid_from") or target_date_str,
            "valid_until": item.get("valid_until"),
            "review_due_at": item.get("review_due_at"),
            "stability": item.get("stability", "stable"),
            "sensitivity": item.get("sensitivity", "personal"),
            "extraction_confidence": float(item.get("extraction_confidence", 0.90)),
            "supersedes": item.get("supersedes"),
            "contradicts": item.get("contradicts") or [],
            "provenance": {
                "extraction_method": "llm",
                "prompt_version": "mem-extract-v1",
                "model": f"{config.MEMORY_EXTRACTOR_PROVIDER}:{config.MEMORY_EXTRACTOR_MODEL}"
            },
            "created_at": timestamp_now,
            "updated_at": timestamp_now,
            "reviewed_by": None,
            "reviewed_at": None
        }

        # Sequential deduplication suggestions
        suggestions = run_deduplication(cand, existing_memories, embedder=embedder)
        if suggestions:
            cand["dedup_suggestions"] = suggestions

        candidates.append(cand)
        existing_memories.append(cand)
        new_candidates.append(cand)

        # Log creation event
        log_memory_event(
            event_type="created",
            memory_id=memory_id,
            previous_status=None,
            new_status="candidate"
        )

    save_all_memories(existing_memories)
    return new_candidates


def review_memory(memory_id: str, action: str, new_content: Optional[str] = None) -> bool:
    """
    Review candidate memory with specified action (approve, reject, edit).
    """
    logger.info(f"Reviewing memory {memory_id} with action {action}")
    memories = load_all_memories()

    found_idx = -1
    for i, m in enumerate(memories):
        if m.get("memory_id") == memory_id:
            found_idx = i
            break

    if found_idx == -1:
        logger.error(f"Memory with ID {memory_id} not found")
        return False

    target = memories[found_idx]
    prev_status = target.get("status")

    timestamp_now = get_current_timestamp()

    if action == "approve":
        target["status"] = "approved"
        target["reviewed_by"] = "user"
        target["reviewed_at"] = timestamp_now
        target["updated_at"] = timestamp_now
        log_memory_event(
            event_type="approved",
            memory_id=memory_id,
            previous_status=prev_status,
            new_status="approved"
        )
    elif action == "reject":
        target["status"] = "rejected"
        target["reviewed_by"] = "user"
        target["reviewed_at"] = timestamp_now
        target["updated_at"] = timestamp_now
        log_memory_event(
            event_type="rejected",
            memory_id=memory_id,
            previous_status=prev_status,
            new_status="rejected"
        )
    elif action == "edit":
        if not new_content:
            logger.error("Content is required for edit action")
            return False
        before_content = target.get("content", "")
        target["content"] = new_content
        target["status"] = "approved"
        target["reviewed_by"] = "user"
        target["reviewed_at"] = timestamp_now
        target["updated_at"] = timestamp_now

        changes = {
            "content": {
                "before": before_content,
                "after": new_content
            }
        }
        log_memory_event(
            event_type="edited",
            memory_id=memory_id,
            previous_status=prev_status,
            new_status="approved",
            changes=changes
        )
    else:
        logger.error(f"Unknown action: {action}")
        return False

    save_all_memories(memories)

    # Re-project approved memories markdown
    project_approved_memories()
    return True


def estimate_tokens(text: str) -> int:
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # Fallback approximation for mixed Japanese and English text
        return int(len(text) * 1.2)


def compile_context(for_purpose: str = "make-target") -> dict:
    """
    Compile approved memories to be injected as ContextPack.
    - Resolves automatic expiration of valid_until / review_due_at.
    - Excludes non-active items.
    - Prioritizes based on confidence, stability, and creation timestamp.
    - Selects items within the token budget.
    """
    logger.info(f"Compiling context for purpose: {for_purpose}")
    try:
        memories = load_all_memories()
    except Exception as e:
        logger.error(f"Failed to load memories for compilation fallback: {e}")
        return {
            "context": "",
            "used_memory_ids": [],
            "estimated_tokens": 0,
            "excluded": []
        }

    now_dt = datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d")

    active_approved = []
    excluded = []
    has_changes = False

    for m in memories:
        m_id = m.get("memory_id")
        status = m.get("status")

        if status != "approved":
            continue

        # Check expiration logic
        is_expired = False
        expire_reason = ""

        valid_until = m.get("valid_until")
        if valid_until:
            try:
                # Assuming valid_until is YYYY-MM-DD
                val_dt = datetime.strptime(valid_until, "%Y-%m-%d")
                if now_dt.date() > val_dt.date():
                    is_expired = True
                    expire_reason = "expired"
            except Exception:
                pass

        review_due_at = m.get("review_due_at")
        if review_due_at:
            try:
                # Try parsing as ISO datetime or YYYY-MM-DD
                if "T" in review_due_at:
                    rd_dt = datetime.fromisoformat(review_due_at)
                    if now_dt > rd_dt:
                        is_expired = True
                        expire_reason = "expired"
                else:
                    rd_dt = datetime.strptime(review_due_at, "%Y-%m-%d")
                    if now_dt.date() > rd_dt.date():
                        is_expired = True
                        expire_reason = "expired"
            except Exception:
                pass

        if is_expired:
            m["status"] = "expired"
            m["updated_at"] = get_current_timestamp()
            has_changes = True
            log_memory_event(
                event_type="expired",
                memory_id=m_id,
                previous_status="approved",
                new_status="expired",
                reason="Automatic expiration during context compilation"
            )
            excluded.append({"memory_id": m_id, "reason": "expired"})
            continue

        # Check valid_from (not yet valid)
        valid_from = m.get("valid_from")
        if valid_from:
            try:
                vf_dt = datetime.strptime(valid_from, "%Y-%m-%d")
                if now_dt.date() < vf_dt.date():
                    excluded.append({"memory_id": m_id, "reason": "not_yet_valid"})
                    continue
            except Exception:
                pass

        active_approved.append(m)

    if has_changes:
        try:
            save_all_memories(memories)
            project_approved_memories()
        except Exception as e:
            logger.error(f"Failed to update memories database on compile expiration: {e}")

    # Prioritization sorting
    # 1. extraction_confidence (descending)
    # 2. stability (stable=1, other=0) (descending)
    # 3. created_at (descending)
    def priority_key(item):
        confidence = float(item.get("extraction_confidence", 0.0))
        stability_score = 1 if item.get("stability") == "stable" else 0
        created_at_str = item.get("created_at") or ""
        return (confidence, stability_score, created_at_str)

    sorted_active = sorted(active_approved, key=priority_key, reverse=True)

    used_memory_ids = []
    budget = config.MEMORY_CONTEXT_MAX_TOKENS
    context_lines = []
    total_tokens = 0

    # Format long term memories section title
    section_title = "## 根拠付き参考情報（長期記憶）\n"
    total_tokens += estimate_tokens(section_title)

    for m in sorted_active:
        m_id = m.get("memory_id")
        kind = m.get("kind", "preference")
        key = m.get("memory_key", "")
        content = m.get("content", "")

        # Format item
        item_text = f"- [{kind}] (Key: {key}): {content}\n"
        tokens = estimate_tokens(item_text)

        if total_tokens + tokens > budget:
            excluded.append({"memory_id": m_id, "reason": "token_limit_exceeded"})
            continue

        context_lines.append(item_text)
        total_tokens += tokens
        used_memory_ids.append(m_id)

    context_str = ""
    if context_lines:
        context_str = section_title + "".join(context_lines)

    return {
        "context": context_str,
        "used_memory_ids": used_memory_ids,
        "estimated_tokens": total_tokens,
        "excluded": excluded
    }
