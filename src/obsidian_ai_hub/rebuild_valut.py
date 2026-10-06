"""Rebuild the Obsidian vault indexes in md-hybrid-search (per-Vault)."""

from __future__ import annotations

import logging

from md_hybrid_search import ConfigMismatchError

from obsidian_ai_hub import sync_valut
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


def rebuild_one_vault(vault_id: str) -> None:
    """Rebuild a single Vault index and record its identity on success."""
    from obsidian_ai_hub.sync_valut import _write_identity

    descriptor = config.resolve_vault_descriptor(vault_id)
    search_index = sync_valut.build_vault_search_index(
        descriptor.vault_id, check_identity=False
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
        except (ConfigMismatchError, FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
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
