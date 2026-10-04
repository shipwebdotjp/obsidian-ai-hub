"""Source Adapter contract for the generic retrieval index.

Each source of truth (long-term memory today; AI conversations or coding
history in the future) implements this contract so the retrieval service can
index, update, and forget documents without knowing domain details.

The adapter's own store owns deletion and read boundaries: the retrieval
service never deletes source rows, and search results are re-validated
against the source of truth before being returned.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class SourceAdapter(Protocol):
    """Contract for a retrievable source corpus."""

    source_type: str

    def build_index_text(self, record: dict) -> str:
        """Return the canonical text to embed for a source record."""
        ...

    def is_indexable(self, record: dict, now: datetime | None = None) -> bool:
        """Return True when the record should be present in the index."""
        ...

    def load_record(self, source_id: str) -> dict | None:
        """Load the current source-of-truth record, or None when gone."""
        ...

    def is_record_valid(self, record: dict, now: datetime | None = None) -> bool:
        """Re-validate approval/validity of a loaded record for search."""
        ...
