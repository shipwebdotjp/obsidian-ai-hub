"""Agent-facing memory tools: search (read-only) and candidate creation."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.memory.models import (
    MEMORY_COLUMNS,
    generate_memory_id,
    get_current_timestamp,
    normalize_content,
    serialize_memory,
)
from obsidian_ai_hub.memory.store import log_memory_event
from obsidian_ai_hub.utils.topics import normalize_topics

logger = logging.getLogger(__name__)

ALLOWED_KINDS = frozenset(
    {"preference", "decision_policy", "fact", "commitment", "pattern", "episode"}
)

# Canonical timezone for valid_from / observed_at written by agent tools.
# Runtime normalizes "now" to JST before passing, but defensively re-anchor here
# so naive datetimes cannot accidentally land on yesterday/tomorrow.
JST = ZoneInfo("Asia/Tokyo")

# Allowlist for trusted IDs that flow into resource paths / logs.
# Generated IDs are hex/UUID-like, so this is a tight, safe character set.
_ALLOWED_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")

# ---------------------------------------------------------------------------
# Search helpers (embedding fallback)
# ---------------------------------------------------------------------------


def _normalize_for_search(text: str) -> str:
    """NFKC + lower for search comparison; keeps spaces for tokenization."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    return text


def _tokenize(text: str) -> list[str]:
    """Tokenize for fallback scoring.

    Splits on whitespace and punctuation, keeps Japanese word characters.
    Returns unique tokens (lower, NFKC) preserving order, filtered min length 1.
    """
    norm = _normalize_for_search(text)
    # Replace common Japanese delimiters with space before extracting tokens.
    # The middle dot "・" (U+30FB) is within 0x30A0-0x30FF but is a separator, not a word char.
    norm = norm.replace("・", " ").replace("、", " ").replace("。", " ")
    norm = norm.replace(",", " ").replace("，", " ")
    # Use explicit ranges that exclude separators like "・", "、", "。"
    # Hiragana: 3040-309F, Katakana (without middle dot): 30A0-30FA + 30FC-30FF, Kanji: 4E00-9FFF
    tokens = re.findall(r"[a-zA-Z0-9_\u3040-\u309F\u30A0-\u30FA\u30FC-\u30FF\u4E00-\u9FFF]+", norm)
    seen: set[str] = set()
    out: list[str] = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    # If no tokens (e.g. only symbols), fallback to whole normalized string
    if not out and norm.strip():
        out = [norm.strip()]
    return out


def _fallback_score(query: str, memory: dict) -> float:
    """Compute token-match score across content, memory_key, topics, tags.

    Scoring weights (higher = more relevant):
      - content substring (normalized query in normalized content): +3.0
      - content token overlap: +1.0 per matched token
      - memory_key token/ substring: +2.0 per matched token / +2.5 if exact substring
      - topics exact token match: +2.0 per topic
      - tags exact/partial match: +1.5 per tag
    """
    q_norm = _normalize_for_search(query)
    q_tokens = _tokenize(query)
    if not q_norm or not q_tokens:
        return 0.0

    score = 0.0

    content = memory.get("content") or ""
    c_norm = _normalize_for_search(content)
    c_tokens = set(_tokenize(content))

    # Content substring
    if q_norm.strip() and q_norm.strip() in c_norm:
        score += 3.0

    # Content token overlap
    for tok in q_tokens:
        if tok in c_tokens:
            score += 1.0
        elif tok in c_norm:
            # partial substring in content even if token boundary differs
            score += 0.5

    # memory_key
    mkey = (memory.get("memory_key") or "")
    mk_norm = _normalize_for_search(mkey)
    mk_tokens = set(_tokenize(mkey))
    if q_norm.strip() and q_norm.strip() in mk_norm and mk_norm:
        score += 2.5
    for tok in q_tokens:
        if tok in mk_tokens:
            score += 2.0
        elif tok in mk_norm and mk_norm:
            score += 0.8

    # topics
    topics = memory.get("topics") or []
    topics_norm = [_normalize_for_search(t) for t in topics]
    topics_tokens = set()
    for t in topics_norm:
        topics_tokens.update(_tokenize(t))
        # also consider whole normalized topic as token
        if t:
            topics_tokens.add(t)
    for tok in q_tokens:
        if tok in topics_tokens:
            score += 2.0

    # tags
    tags = memory.get("tags") or []
    tags_norm = [_normalize_for_search(t) for t in tags]
    tags_tokens = set()
    for t in tags_norm:
        tags_tokens.update(_tokenize(t))
        if t:
            tags_tokens.add(t)
    for tok in q_tokens:
        if tok in tags_tokens:
            score += 1.5
        elif any(tok in tn for tn in tags_norm if tn):
            score += 0.5

    return score


def search_memories(
    query: str,
    kind: Optional[str] = None,
    limit: int = 5,
    now: Optional[datetime] = None,
) -> dict:
    """Search approved, currently valid memories (read-only).

    Uses embedding similarity if available, otherwise token-match fallback.
    Never triggers expiration DB writes.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if kind is not None and kind not in ALLOWED_KINDS:
        raise ValueError(f"kind must be one of {sorted(ALLOWED_KINDS)}; got {kind!r}")
    if limit < 1 or limit > 10:
        raise ValueError("limit must be between 1 and 10")

    from obsidian_ai_hub.memory.context import get_valid_approved_memories_readonly

    active, _ = get_valid_approved_memories_readonly(now=now)

    # Kind filter
    if kind:
        active = [m for m in active if m.get("kind") == kind]

    if not active:
        return {"memories": []}

    # Try embedding path if available
    embedder = None
    try:
        from obsidian_ai_hub.utils.embeddings import get_embedder, cosine_similarity

        embedder = get_embedder()
    except Exception:
        embedder = None

    scored: list[tuple[float, dict]] = []

    if embedder is not None:
        try:
            q_norm = normalize_content(query)
            if not q_norm:
                raise ValueError("empty normalized query")
            q_vec = embedder.embed_query(q_norm)

            # Batch embeddings: avoid N+1 sequential embed_query calls.
            m_norms: list[str] = [
                normalize_content(m.get("content") or "") for m in active
            ]
            indices = [i for i, n in enumerate(m_norms) if n]
            texts = [m_norms[i] for i in indices]
            vecs_by_idx: dict[int, list[float]] = {}
            if texts:
                try:
                    if hasattr(embedder, "embed_documents"):
                        m_vecs = embedder.embed_documents(texts)
                    else:
                        m_vecs = [embedder.embed_query(t) for t in texts]
                    for idx, vec in zip(indices, m_vecs):
                        vecs_by_idx[idx] = vec
                except Exception as e:
                    logger.warning(
                        f"Batch embedding failed, falling back to token scoring: {e}"
                    )

            if not vecs_by_idx:
                # Embedding path failed; fall back to token scoring for all
                scored = [(_fallback_score(query, m), m) for m in active]
            else:
                for i, m in enumerate(active):
                    vec = vecs_by_idx.get(i)
                    if vec is None:
                        scored.append((_fallback_score(query, m), m))
                        continue
                    sim = cosine_similarity(q_vec, vec)
                    fb = _fallback_score(query, m) * 0.05
                    scored.append((sim + fb, m))
        except Exception as e:
            logger.warning(f"Embedding search failed, falling back to token scoring: {e}")
            scored = [(_fallback_score(query, m), m) for m in active]
    else:
        scored = [(_fallback_score(query, m), m) for m in active]

    # Sort by score desc, then by priority (confidence, stability, created_at)
    def priority_key(m: dict) -> tuple[float, int, str]:
        raw_conf = m.get("extraction_confidence")
        conf = float(raw_conf) if raw_conf is not None else 0.0
        stab = 1 if m.get("stability") == "stable" else 0
        created = m.get("created_at") or ""
        return (conf, stab, created)

    # Filter zero-score if we have any positive scores (avoid returning irrelevant)
    has_positive = any(s > 0 for s, _ in scored)
    if has_positive:
        scored = [pair for pair in scored if pair[0] > 0]

    scored.sort(key=lambda x: (x[0], priority_key(x[1])), reverse=True)

    top = [m for _, m in scored[:limit]]

    result_mems: list[dict] = []
    for m in top:
        result_mems.append(
            {
                "memory_id": m.get("memory_id"),
                "kind": m.get("kind"),
                "content": m.get("content"),
                "topics": m.get("topics") or [],
                "tags": m.get("tags") or [],
                "memory_key": m.get("memory_key") or "",
                "stability": m.get("stability"),
                "evidence": (m.get("evidence") or [])[:1],
                "valid_from": m.get("valid_from"),
                "valid_until": m.get("valid_until"),
            }
        )

    return {"memories": result_mems}


# ---------------------------------------------------------------------------
# Candidate creation (trusted context)
# ---------------------------------------------------------------------------

def _verify_evidence_quote(evidence_quote: Optional[str], user_content: str) -> str:
    """Verify evidence_quote is substring of user_content; fallback otherwise.

    Returns a verified quote string (truncated to 500 chars).
    """
    user_norm = _normalize_for_search(user_content or "")
    if evidence_quote and evidence_quote.strip():
        quote_norm = _normalize_for_search(evidence_quote.strip())
        # Check substring after normalization (case-insensitive for latin)
        if quote_norm and quote_norm in user_norm:
            # Return original quote trimmed
            return evidence_quote.strip()[:500]
        # Also check raw substring (without normalization) for robustness
        if evidence_quote.strip() in (user_content or ""):
            return evidence_quote.strip()[:500]
    # Fallback: use user_content truncated
    fallback = (user_content or "").strip()
    if len(fallback) > 500:
        fallback = fallback[:500]
    return fallback


def _normalize_memory_key(raw: Optional[str]) -> str:
    """Normalize memory_key to its [a-z0-9-]{1,64} lowercased form.

    Returns "" for None or empty input. Raises ValueError when the caller
    supplied a non-empty string that does not match the technical key format
    so the LLM gets a clear, immediate rejection rather than a silent
    downgrade that would look identical to "not provided".
    """
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError("memory_key must be a string")
    key = raw.strip().lower()
    if not key:
        return ""
    if not re.fullmatch(r"[a-z0-9-]{1,64}", key):
        raise ValueError(
            "memory_key must be 1-64 chars of [a-z0-9-] (lowercased). "
            "v1 does not transliterate Japanese; omit the key for content-derived keys."
        )
    return key


def _validate_trusted_id(value: Any, name: str) -> str:
    """Validate trusted ID (session_id, user_message_id, ...) before embedding
    it in evidence URI or logs. Returns the value if it matches the allowlist.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    if not _ALLOWED_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{name} contains disallowed characters")
    return value


def _resolve_today(now_val: Any) -> tuple[datetime, str]:
    """Resolve a canonical Asia/Tokyo datetime + YYYY-MM-DD string.

    Datetime inputs are normalized to JST so naive callers cannot accidentally
    store yesterday/tomorrow relative to the user's wall clock.
    """
    if isinstance(now_val, datetime):
        now_dt = now_val
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=JST)
        else:
            now_dt = now_dt.astimezone(JST)
        return now_dt, now_dt.date().isoformat()

    if isinstance(now_val, str) and now_val:
        # Try full ISO datetime first
        try:
            dt = datetime.fromisoformat(now_val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
            else:
                dt = dt.astimezone(JST)
            return dt, dt.date().isoformat()
        except Exception:
            pass
        # Try YYYY-MM-DD fallback
        try:
            dt = datetime.strptime(now_val[:10], "%Y-%m-%d").replace(tzinfo=JST)
            return dt, dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # Final fallback: now in JST
    now_dt = datetime.now(JST)
    return now_dt, now_dt.date().isoformat()


def create_memory_candidate(
    *,
    content: str,
    kind: str,
    memory_key: Optional[str] = None,
    topics: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    evidence_quote: Optional[str] = None,
    rationale: Optional[str] = None,
    trusted_ctx: Dict[str, Any],
) -> dict:
    """Create a memory candidate from agent conversation (trusted context).

    Args:
        content: memory body (required, non-empty)
        kind: one of ALLOWED_KINDS
        memory_key: optional technical key; invalid (non-empty but malformed)
                    raises ValueError. None/empty -> stored as "".
        topics/tags: optional lists
        evidence_quote: optional quote from user; verified against user_content
        rationale: optional reason stored in provenance
        trusted_ctx: server-generated dict with agent_id, session_id, run_id,
                     user_message_id, user_content, now (datetime or ISO str)

    Returns:
        dict with status/memory_id/message or error

    Implementation notes:
      - stability is always "tentative"
      - valid_from is today (JST) from trusted now
      - evidence.path uses trusted session/message IDs (allowlist-validated)
      - duplicate check covers approved+candidate via normalized content
      - suggestions saved, LLM assessment deferred
      - Single snapshot reused for both dedup suggestions and duplicate check
    """
    # ---- Validation (fail fast before DB) ----
    if not content or not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"kind must be one of {sorted(ALLOWED_KINDS)}; got {kind!r}")

    if trusted_ctx is None:
        raise ValueError("trusted_ctx is required")
    agent_id = trusted_ctx.get("agent_id")
    session_id = trusted_ctx.get("session_id")
    run_id = trusted_ctx.get("run_id")
    user_message_id = trusted_ctx.get("user_message_id")
    user_content = trusted_ctx.get("user_content") or ""

    if not agent_id or not session_id or not run_id or not user_message_id:
        raise ValueError("trusted_ctx must contain agent_id, session_id, run_id, user_message_id")

    # Validate trusted IDs against allowlist before they flow into URIs / logs.
    session_id = _validate_trusted_id(session_id, "session_id")
    user_message_id = _validate_trusted_id(user_message_id, "user_message_id")
    if not isinstance(agent_id, str) or not agent_id:
        raise ValueError("agent_id must be a non-empty string")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be a non-empty string")

    # Resolve today in JST consistently
    now_dt, today_str = _resolve_today(trusted_ctx.get("now"))

    # Normalize topics/tags
    norm_topics = normalize_topics(topics or [])
    if tags is not None:
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError("tags must be a list of strings")
        # Trim, dedup, limit 10 like normalize_keywords
        seen: set[str] = set()
        norm_tags: list[str] = []
        for t in tags:
            tt = t.strip()
            if not tt or tt in seen:
                continue
            seen.add(tt)
            norm_tags.append(tt)
            if len(norm_tags) >= 10:
                break
    else:
        norm_tags = []

    norm_key = _normalize_memory_key(memory_key)

    verified_quote = _verify_evidence_quote(evidence_quote, user_content)
    # Build evidence with trusted IDs
    evidence = [
        {
            "path": f"agent://sessions/{session_id}/messages/{user_message_id}",
            "quote": verified_quote,
            "observed_at": today_str,
        }
    ]

    provenance: Dict[str, Any] = {
        "extraction_method": "agent_conversation",
        "prompt_version": "agent-propose-v1",
        "agent_id": agent_id,
        "session_id": session_id,
        "run_id": run_id,
        "user_message_id": user_message_id,
    }
    if rationale and isinstance(rationale, str) and rationale.strip():
        provenance["rationale"] = rationale.strip()[:1000]

    # Build candidate dict (without dedup fields yet)
    memory_id = generate_memory_id(today_str)
    timestamp = get_current_timestamp()
    cand: Dict[str, Any] = {
        "schema_version": 1,
        "memory_id": memory_id,
        "status": "candidate",
        "kind": kind,
        "memory_key": norm_key,
        "content": content.strip(),
        "topics": norm_topics,
        "tags": norm_tags,
        "evidence": evidence,
        "valid_from": today_str,
        "valid_until": None,
        "review_due_at": None,
        "stability": "tentative",
        "sensitivity": "personal",
        "extraction_confidence": 0.9,
        "supersedes": None,
        "contradicts": [],
        "provenance": provenance,
        "created_at": timestamp,
        "updated_at": timestamp,
        "reviewed_by": None,
        "reviewed_at": None,
        "dedup_suggestions": None,
        "dedup_assessment": None,
    }

    cand_norm = normalize_content(cand["content"])

    # ---- Atomic duplicate check + insert ----
    # Single snapshot inside BEGIN IMMEDIATE handles both exact-content
    # duplicate detection and dedup_suggestions, avoiding extra full-table scans.
    conn = get_db_connection()
    suggestions: Optional[List[dict]] = None
    existing_snapshot: List[dict] = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT memory_id, content, status FROM memories WHERE status IN ('approved','candidate')"
        )
        rows = cursor.fetchall()
        for row in rows:
            existing_content = row["content"] or ""
            if normalize_content(existing_content) == cand_norm:
                # Duplicate found - rollback and return error
                conn.rollback()
                return {
                    "error": "同一内容の記憶が既に存在します",
                    "existing_memory_id": row["memory_id"],
                    "existing_status": row["status"],
                }

        # For dedup suggestions reuse the same snapshot (only the rows we read).
        # Other fields used by run_deduplication are filled with empty defaults
        # so the similarity check still has a stable shape.
        for row in rows:
            existing_snapshot.append(
                {
                    "memory_id": row["memory_id"],
                    "content": row["content"],
                    "status": row["status"],
                    "memory_key": "",
                    "topics": [],
                    "tags": [],
                }
            )

        # Compute dedup suggestions from the same snapshot (no second full scan).
        # We only need similarity against approved memories; non-approved rows are
        # filtered out of the comparison.
        try:
            from obsidian_ai_hub.memory.dedup import run_deduplication
            from obsidian_ai_hub.utils.embeddings import get_embedder as _get_embedder

            embedder = None
            try:
                embedder = _get_embedder()
            except Exception:
                embedder = None
            sug = run_deduplication(cand, existing_snapshot, embedder=embedder)
            if sug:
                suggestions = sug
                cand["dedup_suggestions"] = suggestions
        except Exception as e:
            logger.warning(f"Failed to compute dedup suggestions: {e}")
            suggestions = None

        # No duplicate - insert
        db_row = serialize_memory(cand)
        columns = ", ".join(MEMORY_COLUMNS)
        placeholders = ", ".join("?" for _ in MEMORY_COLUMNS)
        cursor.execute(
            f"INSERT INTO memories ({columns}) VALUES ({placeholders})",
            tuple(db_row.get(col) for col in MEMORY_COLUMNS),
        )
        # Log event within same transaction
        log_memory_event(
            event_type="created",
            memory_id=memory_id,
            previous_status=None,
            new_status="candidate",
            conn=conn,
            actor="agent",
        )
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception(f"Failed to create memory candidate: {e}")
        raise
    finally:
        conn.close()

    return {
        "status": "candidate_created",
        "memory_id": memory_id,
        "message": "長期記憶の候補として保存しました。メモリ画面で確認・承認できます。",
    }
