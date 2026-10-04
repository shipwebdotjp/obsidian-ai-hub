"""Canonical index text, content hashes, and model fingerprints."""

from __future__ import annotations

import hashlib


def current_model_fingerprint() -> str:
    """Return the embedding model fingerprint used for new index writes.

    The retrieval index shares the Vault index embedding model
    (``VAULT_INDEX_EMBEDDER_MODEL``). The model name is stored in the catalog
    so a model change invalidates stale vectors instead of silently mixing
    embedding spaces.
    """
    from obsidian_ai_hub.utils import config

    return str(config.VAULT_INDEX_EMBEDDER_MODEL)


def build_memory_index_text(memory: dict) -> str:
    """Build the canonical text to embed for a memory record."""
    content = (memory.get("content") or "").strip()
    extras: list[str] = []
    for topic in memory.get("topics") or []:
        if topic and str(topic).strip():
            extras.append(str(topic).strip())
    for tag in memory.get("tags") or []:
        if tag and str(tag).strip():
            extras.append(str(tag).strip())
    memory_key = (memory.get("memory_key") or "").strip()
    if memory_key:
        extras.append(memory_key)
    if extras:
        return content + "\n" + " ".join(extras)
    return content


def content_hash_for(index_text: str) -> str:
    """Return the SHA-256 hex digest of the canonical index text."""
    return hashlib.sha256(index_text.encode("utf-8")).hexdigest()


def chroma_doc_id(source_type: str, source_id: str) -> str:
    """Return the Chroma document id for a catalog entry."""
    return f"{source_type}:{source_id}"


def parse_chroma_doc_id(doc_id: str) -> tuple[str, str] | None:
    """Split a Chroma document id back into (source_type, source_id)."""
    if ":" not in doc_id:
        return None
    source_type, _, source_id = doc_id.partition(":")
    if not source_type or not source_id:
        return None
    return source_type, source_id
