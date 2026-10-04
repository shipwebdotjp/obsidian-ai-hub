"""Generic retrieval foundation.

The first corpus is approved long-term memories. AI conversations and coding
history can be added later behind the same :class:`SourceAdapter` contract.

Design authority: the ``retrieval_documents`` SQLite catalog is the source of
truth (source id, content hash, model fingerprint, indexed_at). Chroma is a
derived vector index: candidates are only returned when the catalog entry
matches the current source of truth.
"""

from obsidian_ai_hub.retrieval.adapters import SourceAdapter
from obsidian_ai_hub.retrieval.service import (
    RetrievalSyncError,
    RetrievalUnavailableError,
)

__all__ = [
    "SourceAdapter",
    "RetrievalSyncError",
    "RetrievalUnavailableError",
]
