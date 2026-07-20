from __future__ import annotations

import logging
from datetime import datetime, timezone

from obsidian_ai_hub.utils import config

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.memory.models import (
    MEMORY_COLUMNS,
    estimate_tokens,
    get_current_timestamp,
    serialize_memory,
)
from obsidian_ai_hub.memory.store import load_all_memories, log_memory_event

logger = logging.getLogger(__name__)


def get_currently_valid_approved_memories() -> tuple[list[dict], list[dict]]:
    """
    Check and update expiration status for all approved memories.
    Returns:
        (active_approved, excluded) where:
            active_approved: list of currently valid, approved memory dicts
            excluded: list of dicts with {"memory_id": str, "reason": str} for items excluded due to being expired or not yet valid
    """
    logger.info("Checking and loading currently valid approved memories")
    memories = load_all_memories()

    now_dt = datetime.now(timezone.utc)
    active_approved = []
    excluded = []
    has_changes = False

    conn = get_db_connection()
    try:
        with conn:
            for m in memories:
                m_id = m.get("memory_id")
                status = m.get("status")

                if status != "approved":
                    continue

                # Check expiration logic
                is_expired = False

                valid_until = m.get("valid_until")
                if valid_until:
                    try:
                        # Assuming valid_until is YYYY-MM-DD
                        val_dt = datetime.strptime(valid_until, "%Y-%m-%d")
                        if now_dt.date() > val_dt.date():
                            is_expired = True
                    except Exception:
                        pass

                review_due_at = m.get("review_due_at")
                if review_due_at:
                    try:
                        # Try parsing as ISO datetime or YYYY-MM-DD
                        if "T" in review_due_at:
                            rd_dt = datetime.fromisoformat(review_due_at)
                            if rd_dt.tzinfo is None:
                                rd_dt = rd_dt.replace(tzinfo=timezone.utc)
                            if now_dt > rd_dt:
                                is_expired = True
                        else:
                            rd_dt = datetime.strptime(
                                review_due_at, "%Y-%m-%d"
                            ).replace(tzinfo=timezone.utc)
                            if now_dt.date() > rd_dt.date():
                                is_expired = True
                    except Exception:
                        pass

                if is_expired:
                    m["status"] = "expired"
                    m["updated_at"] = get_current_timestamp()
                    has_changes = True

                    # Update target in DB
                    db_row = serialize_memory(m)
                    set_clause = ", ".join(
                        f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                    )
                    values = [
                        db_row.get(col) for col in MEMORY_COLUMNS if col != "memory_id"
                    ] + [m_id]
                    conn.execute(
                        f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                    )

                    log_memory_event(
                        event_type="expired",
                        memory_id=m_id,
                        previous_status="approved",
                        new_status="expired",
                        reason="Automatic expiration during validity check",
                        conn=conn,
                    )
                    excluded.append({"memory_id": m_id, "reason": "expired"})
                    continue

                # Check valid_from (not yet valid)
                valid_from = m.get("valid_from")
                if valid_from:
                    try:
                        vf_dt = datetime.strptime(valid_from, "%Y-%m-%d")
                        if now_dt.date() < vf_dt.date():
                            excluded.append(
                                {"memory_id": m_id, "reason": "not_yet_valid"}
                            )
                            continue
                    except Exception:
                        pass

                active_approved.append(m)
    finally:
        conn.close()

    if has_changes:
        from obsidian_ai_hub.memory.projection import project_approved_memories

        try:
            project_approved_memories()
        except Exception as e:
            logger.error(f"Failed to update memories database on validity check: {e}")

    return active_approved, excluded


def compile_context(for_purpose: str = "make-target") -> dict:
    """
    Compile approved memories to be injected as ContextPack.
    - Resolves automatic expiration of valid_until / review_due_at.
    - Excludes non-active items.
    - Prioritizes based on confidence, stability, and creation timestamp.
    - Selects items within the token budget.
    """
    logger.info(f"Compiling context for purpose: {for_purpose}")
    excluded = []
    try:
        active_approved, initial_excluded = get_currently_valid_approved_memories()
        excluded.extend(initial_excluded)
    except Exception as e:
        logger.error(f"Failed to load memories for compilation fallback: {e}")
        return {
            "context": "",
            "used_memory_ids": [],
            "estimated_tokens": 0,
            "excluded": [],
        }

    # Prioritization sorting
    # 1. extraction_confidence (descending)
    # 2. stability (stable=1, other=0) (descending)
    # 3. created_at (descending)
    def priority_key(item):
        raw_conf = item.get("extraction_confidence")
        confidence = float(raw_conf) if raw_conf is not None else 0.0
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
        "excluded": excluded,
    }
