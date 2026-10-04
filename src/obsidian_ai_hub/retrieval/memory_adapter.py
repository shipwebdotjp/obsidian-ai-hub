"""Long-term memory Source Adapter and pre-DB-write sync helpers.

Deletion/validity contract (operation scenario):

- Memory delete: Chroma vectors are deleted *before* the ``memories`` /
  ``retrieval_documents`` rows are touched. A Chroma failure aborts the
  delete; the source rows are never modified first.
- DB write: the ``memories`` row and the ``retrieval_documents`` catalog row
  are written in the same SQLite transaction. On DB failure the caller rolls
  back (catalog included) and best-effort restores the previous Chroma
  vector; any leftover fragment is excluded from search by hash comparison.
- Search: Chroma candidates are re-validated against approval, validity,
  and the catalog hash/model before anything is returned.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from obsidian_ai_hub.retrieval import catalog as _catalog
from obsidian_ai_hub.retrieval.adapters import SourceAdapter
from obsidian_ai_hub.retrieval.documents import (
    build_memory_index_text,
    chroma_doc_id,
    content_hash_for,
    current_model_fingerprint,
)

logger = logging.getLogger(__name__)

SOURCE_TYPE = "memory"


class MemorySourceAdapter(SourceAdapter):
    """Source Adapter for approved user-scope long-term memories."""

    source_type = SOURCE_TYPE

    def build_index_text(self, record: dict) -> str:
        return build_memory_index_text(record)

    def is_indexable(self, record: dict, now: datetime | None = None) -> bool:
        if record.get("status") != "approved":
            return False
        if (record.get("scope") or "user") != "user":
            return False
        return self.is_record_valid(record, now=now)

    def load_record(self, source_id: str) -> dict | None:
        from obsidian_ai_hub.memory.store import get_memory

        return get_memory(source_id)

    def is_record_valid(self, record: dict, now: datetime | None = None) -> bool:
        if record.get("status") != "approved":
            return False
        if (record.get("scope") or "user") != "user":
            return False
        from obsidian_ai_hub.memory.context import _check_memory_validity
        from datetime import timezone

        now_dt = now or datetime.now(timezone.utc)
        is_active, _ = _check_memory_validity(record, now_dt)
        return is_active


def prepare_memory_index_write(memory: dict) -> dict:
    """Execute the Chroma side of a memory write *before* the DB write.

    Returns a catalog action for the caller to apply inside its own SQLite
    transaction via :func:`apply_memory_catalog_write`:

    - ``{"op": "upsert", "content_hash": ..., "model": ...}``
    - ``{"op": "delete"}`` when the memory must not be indexed
    - ``{"op": "skip"}`` when no embedder is available (vector search
      degrades to token fallback; the DB write proceeds)

    Raises :class:`RetrievalSyncError` when the vector write fails so the
    caller aborts before touching the source of truth.
    """
    from obsidian_ai_hub.retrieval.service import (
        RetrievalSyncError,
        embed_texts,
        get_embedder_for_model,
    )

    adapter = MemorySourceAdapter()
    if not adapter.is_indexable(memory):
        delete_memory_vectors(memory.get("memory_id") or "")
        return {"op": "delete"}

    model = current_model_fingerprint()
    embedder = get_embedder_for_model(model)
    if embedder is None:
        logger.warning(
            "Retrieval embedder unavailable; skipping vector write for %s "
            "(search falls back to token matching)",
            memory.get("memory_id"),
        )
        return {"op": "skip"}

    index_text = adapter.build_index_text(memory)
    content_hash = content_hash_for(index_text)
    try:
        vectors = embed_texts(embedder, [index_text])
        from obsidian_ai_hub.retrieval import chroma_store

        chroma_store.upsert_vectors(
            ids=[chroma_doc_id(SOURCE_TYPE, memory["memory_id"])],
            embeddings=vectors,
            documents=[index_text],
            metadatas=[{"source_type": SOURCE_TYPE, "source_id": memory["memory_id"]}],
        )
    except Exception as e:
        raise RetrievalSyncError(
            f"Retrieval vector upsert failed for {memory.get('memory_id')}: {e}"
        ) from e
    return {"op": "upsert", "content_hash": content_hash, "model": model}


def apply_memory_catalog_write(
    conn: sqlite3.Connection, memory_id: str, action: dict
) -> None:
    """Apply the catalog side of ``prepare_memory_index_write`` in the DB txn."""
    op = action.get("op")
    if op == "upsert":
        _catalog.upsert_entry(
            SOURCE_TYPE,
            memory_id,
            action["content_hash"],
            action["model"],
            conn=conn,
        )
    elif op == "delete":
        _catalog.delete_entry(SOURCE_TYPE, memory_id, conn=conn)
    # "skip": leave the catalog untouched; hash mismatch excludes fragments.


def restore_memory_vector(memory: dict | None) -> None:
    """Best-effort restore of a memory vector after a DB failure.

    Never raises; leftover fragments are excluded from search by hash
    comparison when restoration is impossible.
    """
    if not memory:
        return
    try:
        # Re-embeds the previous content and upserts it back. When the
        # embedder is unavailable there is nothing to restore; hash
        # comparison against the rolled-back catalog keeps search consistent.
        prepare_memory_index_write(memory)
    except Exception as e:
        logger.warning(
            "Failed to restore retrieval vector for %s: %s",
            memory.get("memory_id"),
            e,
        )


def delete_memory_vectors(memory_id: str) -> None:
    """Delete Chroma vectors for a memory. Raises on failure.

    Always attempts the physical forget: deleting a missing id is a
    no-op, and a user-requested forget must not leave vector text on disk
    just because the catalog row is already gone.
    """
    from obsidian_ai_hub.retrieval import chroma_store
    from obsidian_ai_hub.retrieval.service import RetrievalSyncError

    if not memory_id:
        return
    try:
        chroma_store.delete_vectors([chroma_doc_id(SOURCE_TYPE, memory_id)])
    except Exception as e:
        raise RetrievalSyncError(
            f"Retrieval vector delete failed for {memory_id}: {e}"
        ) from e


def _delete_vectors_forced(memory_id: str) -> None:
    """Delete Chroma vectors without consulting the catalog (compensation)."""
    from obsidian_ai_hub.retrieval import chroma_store

    chroma_store.delete_vectors([chroma_doc_id(SOURCE_TYPE, memory_id)])


def prepare_memory_delete(memory_id: str) -> dict | None:
    """Chroma-first delete for the memory-delete scenario.

    Returns the previous catalog entry (for compensation) and raises
    :class:`RetrievalSyncError` when the Chroma delete fails so the caller
    never starts the source delete.
    """
    previous = _catalog.get_entry(SOURCE_TYPE, memory_id)
    delete_memory_vectors(memory_id)
    return previous


def prepare_many(states: dict[str, dict | None]) -> dict[str, dict]:
    """Execute the Chroma side of a multi-memory write before the DB write.

    ``states`` maps memory_id to its post-write dict, or None when the id
    must not be indexed. Returns catalog actions for
    :func:`apply_many_catalog_write`. Raises :class:`RetrievalSyncError` on
    the first vector failure; vectors written earlier in the same batch stay
    applied but are excluded from search by hash comparison until their DB
    rows (and catalog) are updated.
    """
    prepared: dict[str, dict] = {}
    for mid, state in states.items():
        if state is None:
            delete_memory_vectors(mid)
            prepared[mid] = {"op": "delete"}
        else:
            prepared[mid] = prepare_memory_index_write(state)
    return prepared


def apply_many_catalog_write(
    conn: sqlite3.Connection, prepared: dict[str, dict]
) -> None:
    """Apply catalog writes for :func:`prepare_many` inside the DB txn."""
    for mid, action in prepared.items():
        apply_memory_catalog_write(conn, mid, action)


def restore_many(old_states: dict[str, dict | None]) -> None:
    """Best-effort Chroma restore after a DB failure. Never raises."""
    for mid, old in old_states.items():
        try:
            if old is None:
                _delete_vectors_forced(mid)
            else:
                restore_memory_vector(old)
        except Exception as e:
            logger.warning(
                "Failed to restore retrieval vector for %s: %s", mid, e
            )
