"""Rebuild the Obsidian vault indexes in md-hybrid-search (per-Vault)."""

from __future__ import annotations

import logging

from md_hybrid_search import ConfigMismatchError

from obsidian_ai_hub import sync_valut
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


def rebuild_one_vault(vault_id: str) -> None:
    """Rebuild a single Vault index and record its identity on success.

    Rebuild re-creates the index, so the stale-path guard is bypassed: the
    index is constructed directly from the current descriptor path.
    """
    from obsidian_ai_hub.sync_valut import (
        _prepare_model_cache_dir,
        _prepare_storage_paths,
        _write_identity,
    )
    from md_hybrid_search import DirectorySource, SearchIndex
    from obsidian_ai_hub.utils.simple_sbert_embeddings import SimpleSbertEmbeddings

    descriptor = config.resolve_vault_descriptor(vault_id)
    cache_dir = _prepare_model_cache_dir()
    sqlite_path, chroma_path = _prepare_storage_paths(descriptor.vault_id)
    embedder = SimpleSbertEmbeddings(
        model_name=config.VAULT_INDEX_EMBEDDER_MODEL,
        cache_dir=cache_dir,
        allow_network_fallback=config.VAULT_INDEX_ALLOW_NETWORK_FALLBACK,
    )
    search_index = SearchIndex(
        collection_name=config.VAULT_INDEX_COLLECTION_NAME,
        sources=[DirectorySource(str(descriptor.path))],
        sqlite_path=str(sqlite_path),
        chroma_path=str(chroma_path),
        embedder=embedder,
    )
    logger.info("Starting vault index rebuild for '%s'...", descriptor.vault_id)
    search_index.rebuild()
    _write_identity(descriptor.vault_id, descriptor.path)


def rebuild_vaults(vault_ids: list[str] | None = None) -> dict[str, object]:
    """Rebuild all (ID order) or selected Vaults, attempting the rest after failure.

    Unknown Vault IDs fail closed with ``SystemExit(1)``.
    """
    try:
        targets = config.resolve_vault_ids(vault_ids)
    except (KeyError, ValueError, RuntimeError) as exc:
        logger.error("Vault index rebuild failed: %s", exc)
        raise SystemExit(1) from exc
    succeeded: list[str] = []
    failed: dict[str, str] = {}
    for vid in targets:
        try:
            rebuild_one_vault(vid)
            succeeded.append(vid)
            logger.info("Vault index rebuild completed for '%s'.", vid)
        except (ConfigMismatchError, FileNotFoundError, RuntimeError, ValueError) as exc:
            logger.error("Vault index rebuild failed for '%s': %s", vid, exc)
            failed[vid] = str(exc)
    if failed:
        raise SystemExit(1)
    return {"succeeded": succeeded, "failed": failed}


def main(vault_ids: list[str] | None = None):
    """Rebuild the vault index(es) in md-hybrid-search."""
    try:
        return rebuild_vaults(vault_ids)
    except SystemExit:
        raise
    except (ConfigMismatchError, FileNotFoundError, RuntimeError, ValueError) as exc:
        logger.error("Vault index rebuild failed: %s", exc)
        raise SystemExit(1) from exc
