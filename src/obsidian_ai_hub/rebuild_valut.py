"""Rebuild the Obsidian vault index in md-hybrid-search."""

from __future__ import annotations

import logging

from md_hybrid_search import ConfigMismatchError

from obsidian_ai_hub import sync_valut

logger = logging.getLogger(__name__)


def main():
    """Rebuild the vault index in md-hybrid-search."""
    try:
        index = sync_valut.build_vault_search_index()
        logger.info("Starting vault index rebuild...")
        index.rebuild()
    except ConfigMismatchError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        logger.error("Vault index rebuild failed: %s", exc)
        raise SystemExit(1) from exc

    logger.info("Vault index rebuild completed successfully.")
