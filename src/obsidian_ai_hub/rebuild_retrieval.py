"""Rebuild the generic retrieval index (first corpus: long-term memory)."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def main():
    """Rebuild the retrieval vector index and catalog from the source of truth.

    Run once after install and again after an embedding model change. There
    is no automatic backfill: routine searches never scan the whole corpus.
    """
    from obsidian_ai_hub.retrieval.service import (
        RetrievalSyncError,
        RetrievalUnavailableError,
        rebuild_memory_index,
    )

    try:
        logger.info("Starting retrieval index rebuild...")
        result = rebuild_memory_index()
    except RetrievalUnavailableError as exc:
        logger.error("Retrieval index rebuild unavailable: %s", exc)
        raise SystemExit(1) from exc
    except RetrievalSyncError as exc:
        logger.error("Retrieval index rebuild failed: %s", exc)
        raise SystemExit(1) from exc

    logger.info("Retrieval index rebuild completed successfully.")
    print(json.dumps(result, ensure_ascii=False, indent=2))
