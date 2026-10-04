"""Query-relevant memory injection over the generic retrieval index.

Uses a deterministic keyword embedder (stand-in for the SBERT model, which
is unavailable in tests) with the real SQLite catalog and a real Chroma
collection on the per-test isolated path.
"""

from datetime import datetime, timezone

import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub.memory import context as ctx
from obsidian_ai_hub.memory.agent_tools import search_memories
from obsidian_ai_hub.retrieval import catalog as catalog
from obsidian_ai_hub.retrieval.service import reset_embedder_cache


class KeywordEmbedder:
    """Deterministic unit-vector embedder over disjoint keyword sets."""

    @staticmethod
    def _vec(text: str) -> list[float]:
        t = (text or "").lower()
        if "cat-key" in t:
            return [1.0, 0.0, 0.0]
        if "dog-key" in t:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


@pytest.fixture
def keyword_embedder(monkeypatch):
    from obsidian_ai_hub.retrieval import service as svc

    fake = KeywordEmbedder()
    monkeypatch.setattr(svc, "get_embedder_for_model", lambda model: fake)
    reset_embedder_cache()
    return fake


def _make_memory(
    memory_id: str,
    content: str,
    *,
    status: str = "candidate",
    scope: str = "user",
    kind: str = "preference",
    injection_mode: str = "relevant",
    valid_until=None,
) -> dict:
    return {
        "schema_version": 1,
        "memory_id": memory_id,
        "status": status,
        "kind": kind,
        "memory_key": f"key-{memory_id}",
        "content": content,
        "topics": [],
        "tags": [],
        "evidence": [],
        "valid_from": "2026-01-01",
        "valid_until": valid_until,
        "review_due_at": None,
        "stability": "tentative",
        "sensitivity": "personal",
        "extraction_confidence": 0.9,
        "supersedes": None,
        "contradicts": [],
        "provenance": {},
        "created_at": "2026-01-01T10:00:00+09:00",
        "updated_at": "2026-01-01T10:00:00+09:00",
        "reviewed_by": None,
        "reviewed_at": None,
        "dedup_suggestions": None,
        "dedup_assessment": None,
        "scope": scope,
        "injection_mode": injection_mode,
    }


def _search_ids(query: str, **kwargs) -> list[str]:
    return [m["memory_id"] for m in search_memories(query, **kwargs)["memories"]]


# ---------------------------------------------------------------------------
# Index lifecycle: upsert / update / expire / delete / model change
# ---------------------------------------------------------------------------


def test_approve_indexes_and_search_finds(keyword_embedder):
    memory.save_all_memories([_make_memory("m_cat", "猫の餌やりは朝に行う cat-key")])
    assert memory.review_memory("m_cat", "approve") is True

    entry = catalog.get_entry("memory", "m_cat")
    assert entry is not None
    assert entry["content_hash"]
    assert entry["model"]

    assert _search_ids("cat-key") == ["m_cat"]


def test_update_replaces_vector_old_content_absent(keyword_embedder):
    memory.save_all_memories([_make_memory("m1", "猫の餌やりは朝に行う cat-key")])
    assert memory.review_memory("m1", "approve") is True
    assert _search_ids("cat-key") == ["m1"]

    res = memory.update_memory_fields("m1", {"content": "犬の散歩は夜に行う dog-key"})
    assert res["updated"] is True

    assert _search_ids("cat-key") == []
    assert _search_ids("dog-key") == ["m1"]


def test_update_to_expired_forgets_vectors(keyword_embedder):
    memory.save_all_memories([
        _make_memory("m1", "猫の餌やりは朝に行う cat-key", valid_until="2099-01-01"),
    ])
    assert memory.review_memory("m1", "approve") is True
    assert _search_ids("cat-key") == ["m1"]

    res = memory.update_memory_fields("m1", {"valid_until": "2020-01-01"})
    assert res["updated"] is True

    assert catalog.get_entry("memory", "m1") is None
    assert _search_ids("cat-key") == []


def test_validity_lapse_expires_row_and_forgets_vectors(
    keyword_embedder, monkeypatch
):
    memory.save_all_memories([
        _make_memory("m1", "猫の餌やりは朝に行う cat-key", valid_until="2099-01-01"),
    ])
    assert memory.review_memory("m1", "approve") is True
    assert _search_ids("cat-key") == ["m1"]

    real_datetime = datetime

    class _FixedNow(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2100, 6, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(ctx, "datetime", _FixedNow)
    active, _ = ctx._resolve_valid_approved_memories()

    assert [m["memory_id"] for m in active] == []
    assert memory.get_memory("m1")["status"] == "expired"
    assert catalog.get_entry("memory", "m1") is None
    assert _search_ids("cat-key") == []


def test_single_delete_forgets_vectors(keyword_embedder):
    memory.save_all_memories([
        _make_memory("m1", "猫の餌やりは朝に行う cat-key"),
        _make_memory("m2", "犬の散歩は夜に行う dog-key"),
    ])
    assert memory.review_memory("m1", "approve") is True
    assert memory.review_memory("m2", "approve") is True
    assert _search_ids("cat-key") == ["m1"]

    res = memory.delete_memory("m1")
    assert res["deleted"] is True

    assert catalog.get_entry("memory", "m1") is None
    assert _search_ids("cat-key") == []
    assert _search_ids("dog-key") == ["m2"]


def test_batch_delete_forgets_vectors(keyword_embedder):
    memory.save_all_memories([
        _make_memory("m1", "猫の餌やりは朝に行う cat-key"),
        _make_memory("m2", "犬の散歩は夜に行う dog-key"),
    ])
    assert memory.batch_review_memories(["m1", "m2"], "approve")["updated"] == [
        "m1",
        "m2",
    ]
    assert _search_ids("cat-key") == ["m1"]

    res = memory.batch_delete_memories(["m1", "m2"])
    assert res["deleted"] == ["m1", "m2"]
    assert catalog.list_entries("memory") == []
    assert _search_ids("cat-key") == []
    assert _search_ids("dog-key") == []


def test_model_fingerprint_mismatch_hides_stale_vectors(
    keyword_embedder, monkeypatch
):
    memory.save_all_memories([_make_memory("m1", "猫の餌やりは朝に行う cat-key")])
    assert memory.review_memory("m1", "approve") is True
    assert _search_ids("cat-key") == ["m1"]

    from obsidian_ai_hub.retrieval import documents
    from obsidian_ai_hub.retrieval import memory_adapter as mem_adapter

    monkeypatch.setattr(documents, "current_model_fingerprint", lambda: "changed-model")
    monkeypatch.setattr(
        mem_adapter, "current_model_fingerprint", lambda: "changed-model"
    )

    # Stale vector + old catalog model: never returned.
    assert _search_ids("cat-key") == []

    # Manual rebuild re-indexes under the new fingerprint.
    from obsidian_ai_hub.retrieval.service import rebuild_memory_index

    result = rebuild_memory_index()
    assert result["indexed"] == 1
    assert result["model"] == "changed-model"
    assert _search_ids("cat-key") == ["m1"]


# ---------------------------------------------------------------------------
# Query-relevant agent injection
# ---------------------------------------------------------------------------


def test_compile_agent_context_selects_per_query(keyword_embedder):
    memory.save_all_memories([
        _make_memory("m_cat", "猫の餌やりは朝に行う cat-key"),
        _make_memory("m_dog", "犬の散歩は夜に行う dog-key"),
    ])
    assert memory.batch_review_memories(["m_cat", "m_dog"], "approve")["updated"] == [
        "m_cat",
        "m_dog",
    ]

    cat_ctx = ctx.compile_agent_context(query="cat-key")
    assert cat_ctx["used_memory_ids"] == ["m_cat"]
    assert "cat-key" in cat_ctx["context"]
    assert "dog-key" not in cat_ctx["context"]

    dog_ctx = ctx.compile_agent_context(query="dog-key")
    assert dog_ctx["used_memory_ids"] == ["m_dog"]


def test_compile_agent_context_empty_on_low_similarity(keyword_embedder):
    memory.save_all_memories([
        _make_memory("m_cat", "猫の餌やりは朝に行う cat-key"),
    ])
    assert memory.review_memory("m_cat", "approve") is True

    assert ctx.compile_agent_context(query="unrelated-zzz") == {
        "context": "",
        "used_memory_ids": [],
        "estimated_tokens": 0,
    }
    assert ctx.compile_agent_context(query=None) == {
        "context": "",
        "used_memory_ids": [],
        "estimated_tokens": 0,
    }


def test_compile_agent_context_always_packed_first(keyword_embedder):
    memory.save_all_memories([
        _make_memory(
            "m_always",
            "台所の掃除は金曜日に行う",
            injection_mode="always",
        ),
        _make_memory("m_cat", "猫の餌やりは朝に行う cat-key"),
    ])
    assert memory.batch_review_memories(["m_always", "m_cat"], "approve")[
        "updated"
    ] == ["m_always", "m_cat"]

    # Unrelated query: only the always memory is injected.
    res = ctx.compile_agent_context(query="unrelated-zzz")
    assert res["used_memory_ids"] == ["m_always"]

    # Relevant query: always still comes first within the shared budget.
    res = ctx.compile_agent_context(query="cat-key")
    assert res["used_memory_ids"][0] == "m_always"
    assert "m_cat" in res["used_memory_ids"]


def test_compile_agent_context_falls_back_without_index():
    # No embedder in tests: lightweight token matching still serves.
    memory.save_all_memories([
        _make_memory("m1", "簡潔な日本語を好む", status="approved"),
    ])
    res = ctx.compile_agent_context(query="簡潔")
    assert res["used_memory_ids"] == ["m1"]


# ---------------------------------------------------------------------------
# injection_mode constraints (model + Web API)
# ---------------------------------------------------------------------------


def test_injection_mode_always_rejected_for_person_scope():
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO people (person_id, display_name, normalized_name) "
                "VALUES ('peo_1', 'Alice', 'alice')"
            )
    finally:
        conn.close()

    person_mem = _make_memory("m_person", "人物メモリ本文", scope="person")
    person_mem["people"] = [{"person_id": "peo_1", "display_name": "Alice"}]
    memory.save_all_memories([person_mem])

    with pytest.raises(ValueError, match="always"):
        memory.update_memory_fields("m_person", {"injection_mode": "always"})


def test_injection_mode_allowed_for_approved_user_scope():
    memory.save_all_memories([_make_memory("m1", "本文")])
    assert memory.review_memory("m1", "approve") is True

    res = memory.update_memory_fields("m1", {"injection_mode": "always"})
    assert res["updated"] is True
    assert memory.get_memory("m1")["injection_mode"] == "always"

    res = memory.update_memory_fields("m1", {"injection_mode": "relevant"})
    assert memory.get_memory("m1")["injection_mode"] == "relevant"

    with pytest.raises(ValueError, match="injection_mode"):
        memory.update_memory_fields("m1", {"injection_mode": "sometimes"})


@pytest.fixture
def loopback_client(api_token, api_auth_headers):
    from fastapi.testclient import TestClient

    from obsidian_ai_hub.web.app import create_app

    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


def _seed_api(memory_id: str, **overrides) -> None:
    mem = _make_memory(memory_id, "APIテスト本文", **overrides)
    existing = memory.load_all_memories()
    memory.save_all_memories(existing + [mem])


def test_edit_api_accepts_always_for_approved_user(loopback_client):
    _seed_api("m_api1", status="approved")
    res = loopback_client.post("/api/v1/memories/m_api1/edit", json={"injection_mode": "always"})
    assert res.status_code == 200, res.text
    assert res.json()["memory"]["injection_mode"] == "always"
    assert memory.get_memory("m_api1")["injection_mode"] == "always"


def test_edit_api_rejects_always_for_person_scope(loopback_client):
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO people (person_id, display_name, normalized_name) "
                "VALUES ('peo_9', 'Bob', 'bob')"
            )
    finally:
        conn.close()

    mem = _make_memory("m_api2", "人物メモリ本文", status="approved", scope="person")
    mem["people"] = [{"person_id": "peo_9", "display_name": "Bob"}]
    memory.save_all_memories([mem])

    res = loopback_client.post("/api/v1/memories/m_api2/edit", json={"injection_mode": "always"})
    assert res.status_code == 400
    assert memory.get_memory("m_api2")["injection_mode"] == "relevant"


def test_edit_api_rejects_unknown_mode(loopback_client):
    _seed_api("m_api3", status="approved")
    res = loopback_client.post("/api/v1/memories/m_api3/edit", json={"injection_mode": "sometimes"})
    assert res.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Vertical scenario: approve -> inject/search -> delete -> absent
# ---------------------------------------------------------------------------


def test_vertical_approve_search_inject_delete_absent(keyword_embedder):
    memory.save_all_memories([_make_memory("m1", "猫の餌やりは朝に行う cat-key")])

    assert memory.review_memory("m1", "approve") is True
    assert _search_ids("cat-key") == ["m1"]
    assert ctx.compile_agent_context(query="cat-key")["used_memory_ids"] == ["m1"]

    assert memory.delete_memory("m1")["deleted"] is True

    assert _search_ids("cat-key") == []
    assert ctx.compile_agent_context(query="cat-key")["used_memory_ids"] == []
    assert catalog.get_entry("memory", "m1") is None
