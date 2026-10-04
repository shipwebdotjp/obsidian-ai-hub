"""Retrieval orchestration: vector search, sync primitives, index rebuild."""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class RetrievalUnavailableError(Exception):
    """The vector index cannot serve this query (not built, model changed,
    embedder missing, or a search failure occurred). Callers fall back to
    lightweight token matching."""


class RetrievalSyncError(Exception):
    """A vector write failed. Callers must abort the source DB change."""


_embedders: dict[str, object] = {}


def reset_embedder_cache() -> None:
    """Drop cached embedders (tests and model-change rebuilds)."""
    _embedders.clear()
    try:
        from obsidian_ai_hub.retrieval import chroma_store

        chroma_store.reset_client_cache()
    except Exception:
        pass


def get_embedder_for_model(model: str):
    """Return a cached embedder for ``model``, or None when unavailable.

    The shared Vault model delegates to the global lazy embedder; other
    model names get their own process-local instance.
    """
    if model in _embedders:
        return _embedders[model]
    from obsidian_ai_hub.utils import config

    embedder = None
    try:
        if model == config.VAULT_INDEX_EMBEDDER_MODEL:
            from obsidian_ai_hub.utils.embeddings import get_embedder

            embedder = get_embedder()
        else:
            from obsidian_ai_hub.utils.simple_sbert_embeddings import (
                SimpleSbertEmbeddings,
            )

            embedder = SimpleSbertEmbeddings(
                model_name=model,
                allow_network_fallback=config.VAULT_INDEX_ALLOW_NETWORK_FALLBACK,
            )
    except Exception as e:
        logger.warning("Retrieval embedder unavailable for model %s: %s", model, e)
        embedder = None
    if embedder is not None:
        _embedders[model] = embedder
    return embedder


def embed_texts(embedder, texts: list[str]) -> list[list[float]]:
    """Embed documents, batching when the embedder supports it."""
    if hasattr(embedder, "embed_documents"):
        return list(embedder.embed_documents(texts))
    return [list(embedder.embed_query(t)) for t in texts]


def _priority_key(memory: dict) -> tuple[float, int, str]:
    raw_conf = memory.get("extraction_confidence")
    confidence = float(raw_conf) if raw_conf is not None else 0.0
    stability_score = 1 if memory.get("stability") == "stable" else 0
    return (confidence, stability_score, memory.get("created_at") or "")


def search_memory_index(
    query: str,
    *,
    kind: str | None = None,
    limit: int = 5,
    threshold: float | None = None,
    now: datetime | None = None,
) -> list[tuple[dict, float]]:
    """Search approved memories via the retrieval index.

    Returns ``[(memory, cosine_similarity)]`` sorted by similarity, then
    confidence, stability, and creation time. Candidates are re-validated
    against the catalog (hash/model) and the source of truth
    (approval/validity); mismatches and deleted rows are never returned.

    Raises :class:`RetrievalUnavailableError` when the index cannot serve
    the query so callers can fall back to token matching.
    """
    from obsidian_ai_hub.memory.models import normalize_content
    from obsidian_ai_hub.retrieval import catalog as _catalog
    from obsidian_ai_hub.retrieval import chroma_store
    from obsidian_ai_hub.retrieval.documents import (
        build_memory_index_text,
        content_hash_for,
        current_model_fingerprint,
        parse_chroma_doc_id,
    )
    from obsidian_ai_hub.retrieval.memory_adapter import (
        SOURCE_TYPE,
        MemorySourceAdapter,
    )

    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if threshold is None:
        from obsidian_ai_hub.utils import config

        threshold = config.MEMORY_AGENT_RETRIEVAL_THRESHOLD

    model = current_model_fingerprint()
    embedder = get_embedder_for_model(model)
    if embedder is None:
        raise RetrievalUnavailableError("embedder unavailable")

    q_norm = normalize_content(query)
    if not q_norm:
        raise ValueError("query must be a non-empty string")
    try:
        if hasattr(embedder, "embed_query"):
            q_vec = list(embedder.embed_query(q_norm))
        else:
            q_vec = list(embed_texts(embedder, [q_norm])[0])
    except Exception as e:
        raise RetrievalUnavailableError(f"query embedding failed: {e}") from e

    n_results = max(limit * 3, 10)
    try:
        res = chroma_store.query_vectors(q_vec, n_results)
    except Exception as e:
        raise RetrievalUnavailableError(f"vector query failed: {e}") from e

    ids = (res.get("ids") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]
    if not ids:
        # Index exists but holds nothing (or nothing relevant stored).
        raise RetrievalUnavailableError("index holds no vectors")

    adapter = MemorySourceAdapter()
    scored: list[tuple[float, dict]] = []
    for doc_id, distance in zip(ids, distances):
        parsed = parse_chroma_doc_id(str(doc_id))
        if parsed is None:
            continue
        source_type, source_id = parsed
        if source_type != SOURCE_TYPE:
            continue
        try:
            similarity = max(-1.0, min(1.0, 1.0 - float(distance)))
        except (TypeError, ValueError):
            continue
        if similarity < threshold:
            continue
        record = adapter.load_record(source_id)
        if record is None:
            continue
        if not adapter.is_record_valid(record, now=now):
            continue
        if kind is not None and record.get("kind") != kind:
            continue
        entry = _catalog.get_entry(source_type, source_id)
        if entry is None:
            continue
        if entry.get("model") != model:
            continue
        expected_hash = content_hash_for(build_memory_index_text(record))
        if entry.get("content_hash") != expected_hash:
            continue
        scored.append((similarity, record))

    scored.sort(key=lambda x: (x[0], _priority_key(x[1])), reverse=True)
    return scored[:limit]


def rebuild_memory_index() -> dict:
    """Rebuild the whole memory corpus index (manual CLI operation).

    Drops the Chroma collection, re-embeds every currently indexable
    approved memory, and rewrites the catalog in one transaction. No
    per-query backfill happens elsewhere; call this after first install or
    an embedding model change.

    Raises :class:`RetrievalUnavailableError` when no embedder is available.
    """
    from obsidian_ai_hub.memory.store import load_all_memories
    from obsidian_ai_hub.retrieval import catalog as _catalog
    from obsidian_ai_hub.retrieval import chroma_store
    from obsidian_ai_hub.retrieval.documents import (
        build_memory_index_text,
        chroma_doc_id,
        content_hash_for,
        current_model_fingerprint,
    )
    from obsidian_ai_hub.retrieval.memory_adapter import (
        SOURCE_TYPE,
        MemorySourceAdapter,
    )

    model = current_model_fingerprint()
    embedder = get_embedder_for_model(model)
    if embedder is None:
        raise RetrievalUnavailableError(
            f"embedder unavailable for model {model}; "
            "index cannot be rebuilt (search falls back to token matching)"
        )

    adapter = MemorySourceAdapter()
    memories = load_all_memories()
    targets = [m for m in memories if adapter.is_indexable(m)]
    targets.sort(key=lambda m: m.get("memory_id") or "")

    if not targets:
        from obsidian_ai_hub.database import get_db_connection

        conn = get_db_connection()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM retrieval_documents WHERE source_type = ?",
                    (SOURCE_TYPE,),
                )
        finally:
            conn.close()
        return {"indexed": 0, "model": model}

    # Embed before touching the serving index: a failure here leaves the
    # current index and catalog untouched.
    texts = [adapter.build_index_text(m) for m in targets]
    try:
        vectors = embed_texts(embedder, texts)
    except Exception as e:
        raise RetrievalSyncError(f"rebuild embedding failed: {e}") from e
    hashes = [content_hash_for(t) for t in texts]

    chroma_store.reset_collection()
    try:
        chroma_store.upsert_vectors(
            [chroma_doc_id(SOURCE_TYPE, m["memory_id"]) for m in targets],
            [list(v) for v in vectors],
            texts,
            [
                {"source_type": SOURCE_TYPE, "source_id": m["memory_id"]}
                for m in targets
            ],
        )
    except Exception as e:
        raise RetrievalSyncError(f"rebuild vector write failed: {e}") from e

    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "DELETE FROM retrieval_documents WHERE source_type = ?",
                (SOURCE_TYPE,),
            )
            for m, h in zip(targets, hashes):
                _catalog.upsert_entry(
                    SOURCE_TYPE, m["memory_id"], h, model, conn=conn
                )
    finally:
        conn.close()

    return {"indexed": len(targets), "model": model}
