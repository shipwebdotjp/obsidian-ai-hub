"""Dedicated Chroma vector store for the generic retrieval index.

This store is intentionally separate from the Vault ``md-hybrid-search``
index: dedicated on-disk path, dedicated collection, cosine space. The
SQLite catalog (:mod:`obsidian_ai_hub.retrieval.catalog`) is the source of
truth; vectors here are derived data and are always re-validated on read.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_clients: dict[str, object] = {}


def reset_client_cache() -> None:
    """Drop cached Chroma clients (used when the configured path changes)."""
    with _lock:
        _clients.clear()


def _client_path() -> str:
    from obsidian_ai_hub.utils import config

    return str(config.RETRIEVAL_CHROMA_PATH)


def _get_client():
    """Return a cached PersistentClient for the configured path."""
    try:
        import chromadb
    except ImportError as e:
        raise RuntimeError(
            "chromadb is required for the retrieval index"
        ) from e
    path = _client_path()
    with _lock:
        client = _clients.get(path)
        if client is None:
            try:
                from chromadb.config import Settings

                client = chromadb.PersistentClient(
                    path=path,
                    settings=Settings(anonymized_telemetry=False),
                )
            except Exception:
                client = chromadb.PersistentClient(path=path)
            _clients[path] = client
        return client


def get_collection():
    """Return the retrieval collection, creating it on first use."""
    from obsidian_ai_hub.utils import config

    client = _get_client()
    return client.get_or_create_collection(
        name=config.RETRIEVAL_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_vectors(
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict],
) -> None:
    """Upsert vectors. Raises on failure so callers can abort the DB write."""
    collection = get_collection()
    collection.upsert(
        ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
    )


def delete_vectors(ids: list[str]) -> None:
    """Delete vectors. Raises on failure so callers can abort the DB write."""
    if not ids:
        return
    collection = get_collection()
    collection.delete(ids=ids)


def query_vectors(
    query_embedding: list[float], n_results: int
) -> dict:
    """Query nearest vectors. Returns Chroma's result dict."""
    collection = get_collection()
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )


def reset_collection() -> None:
    """Drop and recreate the retrieval collection (used by index rebuild)."""
    from obsidian_ai_hub.utils import config

    client = _get_client()
    name = config.RETRIEVAL_COLLECTION_NAME
    try:
        client.delete_collection(name=name)
    except Exception as e:
        logger.info("Retrieval collection reset (delete skipped): %s", e)
    reset_client_cache()
    get_collection()
