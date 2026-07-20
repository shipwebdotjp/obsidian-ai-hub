from __future__ import annotations

import logging

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

_embedder = None


def get_embedder():
    """Return a cached SBERT embedder or ``None`` if unavailable.

    The embedder is created lazily on first call so that importing this module
    never triggers model downloads or heavy torch / transformers imports.
    """
    global _embedder
    if _embedder is not None:
        return _embedder
    try:
        from obsidian_ai_hub.utils.simple_sbert_embeddings import SimpleSbertEmbeddings

        _embedder = SimpleSbertEmbeddings(
            model_name=config.VAULT_INDEX_EMBEDDER_MODEL,
            allow_network_fallback=config.VAULT_INDEX_ALLOW_NETWORK_FALLBACK,
        )
        return _embedder
    except Exception as e:
        logger.warning(
            f"SBERT Embeddings are not available: {e}. Vector search is disabled."
        )
        return None


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = sum(a * a for a in v1) ** 0.5
    norm_b = sum(b * b for b in v2) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)
