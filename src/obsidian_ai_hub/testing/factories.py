"""Stable dict builders for test data.

Values are explicit and deterministic. Timestamps and IDs are fixed strings —
never generated from the current time — so that tests and AI agents can rely on
stable locators and expectations.
"""

from __future__ import annotations

from typing import Any

from obsidian_ai_hub.testing import ensure_test_mode


def make_memory(
    memory_id: str = "test-mem-001",
    status: str = "candidate",
    content: str = "テスト用メモリの本文です。",
    kind: str = "preference",
    topics: list[str] | None = None,
    tags: list[str] | None = None,
    **overrides: Any,
) -> dict:
    """Return a memory record dict suitable for memory.save_all_memories()."""
    ensure_test_mode()
    base = {
        "schema_version": 1,
        "memory_id": memory_id,
        "status": status,
        "kind": kind,
        "memory_key": f"key-{memory_id}",
        "content": content,
        "topics": topics or ["その他"],
        "tags": tags or ["test"],
        "evidence": [],
        "valid_from": "2026-07-01",
        "valid_until": None,
        "review_due_at": None,
        "stability": "stable",
        "sensitivity": "personal",
        "extraction_confidence": 0.9,
        "supersedes": None,
        "contradicts": [],
        "dedup_suggestions": [],
        "provenance": {"extraction_method": "test"},
        "created_at": "2026-07-01T00:00:00+09:00",
        "updated_at": "2026-07-01T00:00:00+09:00",
        "reviewed_by": None,
        "reviewed_at": None,
    }
    base.update(overrides)
    return base
