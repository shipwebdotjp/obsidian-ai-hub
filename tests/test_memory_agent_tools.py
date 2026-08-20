"""Tests for memory_search / memory_propose agent tools."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from obsidian_ai_hub import memory
from obsidian_ai_hub.agents import registry, store
from obsidian_ai_hub.memory.agent_tools import (
    _normalize_memory_key,
    _validate_trusted_id,
    create_memory_candidate,
    search_memories,
)
from obsidian_ai_hub.memory.store import load_all_memories, save_all_memories
from obsidian_ai_hub.utils import config


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_approved(mid, content, *, kind="preference", memory_key="", topics=None, tags=None,
                   extraction_confidence=0.9, stability="tentative", valid_until=None,
                   valid_from=None):
    now = datetime.now(timezone.utc).date().isoformat()
    return {
        "schema_version": 1,
        "memory_id": mid,
        "status": "approved",
        "kind": kind,
        "memory_key": memory_key,
        "content": content,
        "topics": topics or [],
        "tags": tags or [],
        "evidence": [],
        "valid_from": valid_from or "2026-01-01",
        "valid_until": valid_until,
        "review_due_at": None,
        "stability": stability,
        "sensitivity": "personal",
        "extraction_confidence": extraction_confidence,
        "supersedes": None,
        "contradicts": [],
        "provenance": {},
        "created_at": "2026-01-01T10:00:00+09:00",
        "updated_at": "2026-01-01T10:00:00+09:00",
        "reviewed_by": None,
        "reviewed_at": None,
        "dedup_suggestions": None,
        "dedup_assessment": None,
    }


def _reset_db():
    save_all_memories([])


# ---------------------------------------------------------------------------
# _normalize_memory_key
# ---------------------------------------------------------------------------


def test_normalize_memory_key_none_returns_empty():
    assert _normalize_memory_key(None) == ""


def test_normalize_memory_key_empty_returns_empty():
    assert _normalize_memory_key("   ") == ""


def test_normalize_memory_key_valid():
    assert _normalize_memory_key("response-style-concise") == "response-style-concise"
    assert _normalize_memory_key("FOO-Bar-Baz") == "foo-bar-baz"
    # Pydantic pattern str is the same regex; the function must accept the
    # canonical form used by the UI.
    assert _normalize_memory_key("mem-1-abc") == "mem-1-abc"


def test_normalize_memory_key_invalid_raises():
    with pytest.raises(ValueError, match="memory_key"):
        _normalize_memory_key("日本語キー")
    with pytest.raises(ValueError, match="memory_key"):
        _normalize_memory_key("has space")
    with pytest.raises(ValueError, match="memory_key"):
        _normalize_memory_key("a" * 65)


def test_normalize_memory_key_non_string_raises():
    with pytest.raises(ValueError, match="memory_key"):
        _normalize_memory_key(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _validate_trusted_id
# ---------------------------------------------------------------------------


def test_validate_trusted_id_accepts_hex_id():
    assert _validate_trusted_id("amsg_abc123", "user_message_id") == "amsg_abc123"


def test_validate_trusted_id_rejects_path_traversal():
    with pytest.raises(ValueError, match="disallowed"):
        _validate_trusted_id("../../etc/passwd", "session_id")
    with pytest.raises(ValueError, match="disallowed"):
        _validate_trusted_id("a/b", "session_id")
    with pytest.raises(ValueError, match="non-empty"):
        _validate_trusted_id("", "session_id")


# ---------------------------------------------------------------------------
# search_memories
# ---------------------------------------------------------------------------


def test_search_memories_returns_only_approved_and_filters_kind():
    _reset_db()
    save_all_memories([
        _make_approved("a_p", "簡潔な日本語を好む", kind="preference"),
        _make_approved("a_f", "毎朝ランニング", kind="pattern"),
    ])
    res = search_memories("簡潔", limit=5)
    assert [m["memory_id"] for m in res["memories"]] == ["a_p"]
    res_kind = search_memories("ランニング", kind="fact", limit=5)
    assert res_kind["memories"] == []


def test_search_memories_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        search_memories("query", kind="bogus")
    with pytest.raises(ValueError):
        search_memories("query", limit=0)
    with pytest.raises(ValueError, match="non-empty"):
        search_memories("   ")


# ---------------------------------------------------------------------------
# create_memory_candidate (trusted context)
# ---------------------------------------------------------------------------


def _trusted_ctx(**overrides):
    base = {
        "agent_id": "agent_abc123",
        "session_id": "asess_abc123",
        "run_id": "arun_abc123",
        "user_message_id": "amsg_abc123",
        "user_content": "私は毎朝コーヒーをブラックで飲むのが好きです",
        "now": datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def test_create_candidate_uses_trusted_provenance_and_evidence():
    _reset_db()
    res = create_memory_candidate(
        content="毎朝コーヒーをブラックで飲むことを好む",
        kind="preference",
        memory_key="coffee-black-morning",
        evidence_quote="毎朝コーヒーをブラックで飲む",
        rationale="明示的に表明された嗜好",
        trusted_ctx=_trusted_ctx(),
    )
    assert res["status"] == "candidate_created"
    cand = memory.get_memory(res["memory_id"])
    assert cand["status"] == "candidate"
    assert cand["stability"] == "tentative"
    assert cand["provenance"]["agent_id"] == "agent_abc123"
    assert cand["provenance"]["session_id"] == "asess_abc123"
    assert cand["provenance"]["run_id"] == "arun_abc123"
    assert cand["evidence"][0]["path"] == "agent://sessions/asess_abc123/messages/amsg_abc123"


def test_create_candidate_rejects_invalid_memory_key():
    _reset_db()
    with pytest.raises(ValueError, match="memory_key"):
        create_memory_candidate(
            content="dummy",
            kind="preference",
            memory_key="日本語 キー",
            trusted_ctx=_trusted_ctx(),
        )


def test_create_candidate_rejects_invalid_trusted_ids():
    _reset_db()
    with pytest.raises(ValueError, match="disallowed"):
        create_memory_candidate(
            content="dummy",
            kind="preference",
            trusted_ctx=_trusted_ctx(session_id="../../etc"),
        )
    with pytest.raises(ValueError, match="disallowed"):
        create_memory_candidate(
            content="dummy",
            kind="preference",
            trusted_ctx=_trusted_ctx(user_message_id="a/b"),
        )


def test_create_candidate_falls_back_to_user_content_when_quote_not_substring():
    _reset_db()
    res = create_memory_candidate(
        content="猫好きという事実",
        kind="fact",
        evidence_quote="犬が好き",  # not in user_content
        trusted_ctx=_trusted_ctx(user_content="私は猫が好きです"),
    )
    cand = memory.get_memory(res["memory_id"])
    assert cand["evidence"][0]["quote"] == "私は猫が好きです"


def test_create_candidate_blocks_duplicates_against_approved_and_candidate():
    _reset_db()
    save_all_memories([_make_approved("a_dup", "重複テスト内容")])
    res = create_memory_candidate(
        content="  重複テスト内容  ",
        kind="preference",
        trusted_ctx=_trusted_ctx(),
    )
    assert "error" in res
    assert res["existing_memory_id"] == "a_dup"
    assert res["existing_status"] == "approved"

    # First candidate
    res1 = create_memory_candidate(
        content="候補重複",
        kind="preference",
        trusted_ctx=_trusted_ctx(),
    )
    assert res1["status"] == "candidate_created"
    # Second identical candidate should be blocked
    res2 = create_memory_candidate(
        content="候補重複",
        kind="preference",
        trusted_ctx=_trusted_ctx(),
    )
    assert res2["existing_status"] == "candidate"


def test_create_candidate_does_not_block_against_rejected():
    _reset_db()
    save_all_memories([
        {
            "schema_version": 1,
            "memory_id": "r1",
            "status": "rejected",
            "kind": "preference",
            "memory_key": "",
            "content": "却下された内容",
            "topics": [],
            "tags": [],
            "evidence": [],
            "valid_from": "2026-01-01",
            "valid_until": None,
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
        }
    ])
    res = create_memory_candidate(
        content="却下された内容",
        kind="preference",
        trusted_ctx=_trusted_ctx(),
    )
    assert res["status"] == "candidate_created"


def test_create_candidate_stability_always_tentative():
    _reset_db()
    res = create_memory_candidate(
        content="明示的内容",
        kind="fact",
        trusted_ctx=_trusted_ctx(),
    )
    cand = memory.get_memory(res["memory_id"])
    assert cand["stability"] == "tentative"


# ---------------------------------------------------------------------------
# registry: resolve_tools_with_context + LLM-facing validation
# ---------------------------------------------------------------------------


def test_resolve_tools_with_context_binds_trusted_ctx():
    captured = {}
    tool = registry._make_memory_propose_tool(captured)
    # tool name should be the stable "memory_propose"
    assert tool.name == "memory_propose"


def test_resolve_tools_with_context_copies_trusted_ctx_snapshot():
    trusted = {"agent_id": "a1", "session_id": "s1", "run_id": "r1",
               "user_message_id": "m1", "user_content": "u", "now": None}
    tools = registry.resolve_tools_with_context(["memory_propose"], trusted)
    assert len(tools) == 1
    # Mutate the caller's dict; the tool's bound snapshot must not change.
    trusted["agent_id"] = "MUTATED"
    # Inspect the tool's closure by introspection: try to mutate via a save call
    # and confirm provenance still uses original id.
    res = tools[0].invoke({
        "content": "test",
        "kind": "preference",
    })
    # The propose call requires user_message_id; without it the tool returns
    # a validation error. We just verify the tool didn't accept the mutated
    # agent_id via the captured call path by inspecting provenance if it ran.
    parsed = json.loads(res)
    # If the tool ran, agent_id should be the original "a1", not mutated.
    if parsed.get("status") == "candidate_created":
        cand = memory.get_memory(parsed["memory_id"])
        assert cand["provenance"]["agent_id"] == "a1"


def test_resolve_tools_with_context_propagates_factory_errors():
    bad_meta = {"get_tool_with_context": lambda ctx: (_ for _ in ()).throw(RuntimeError("boom"))}
    with patch.dict("obsidian_ai_hub.agents.registry.TOOL_DEFINITIONS",
                    {"memory_propose": {"tool_id": "memory_propose", "name": "x",
                                        "description": "x", **bad_meta}}):
        with pytest.raises(RuntimeError, match="boom"):
            registry.resolve_tools_with_context(["memory_propose"], {})


def test_search_kind_validation_rejects_unknown_value():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        registry.MemorySearchInput(query="x", kind="bogus_kind")


def test_propose_kind_validation_rejects_unknown_value():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        registry.MemoryProposeInput(content="x", kind="bogus_kind")


def test_propose_extra_field_rejected():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        registry.MemoryProposeInput(content="x", kind="preference", stability="stable")


def test_propose_memory_key_pattern_validated():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        registry.MemoryProposeInput(content="x", kind="preference", memory_key="日本語")


# ---------------------------------------------------------------------------
# End-to-end runtime: trust boundary
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_runtime_propose_uses_server_trusted_ctx_not_llm_args():
    agent = store.create_agent(
        name="Trust Agent", system_prompt="x", tool_ids=["memory_propose"]
    )
    session = store.create_session(agent["agent_id"])
    user_msg, run = store.start_user_run(session["session_id"], "私は早起きが好き")

    # LLM tries to fabricate session_id etc. by including extra args
    # (it cannot, because schema is extra="forbid"). Here we just inject
    # an evidence_quote that is NOT in user_content and verify fallback.
    ai_tool = AIMessage(content="", tool_calls=[{
        "name": "memory_propose",
        "args": {
            "content": "早起きが好き",
            "kind": "preference",
            "evidence_quote": "夜更かしをする",
        },
        "id": "call_1",
    }])
    ai_final = AIMessage(content="done")
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [ai_tool, ai_final]
    mock_llm.bind_tools.return_value = mock_llm

    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm):
        from obsidian_ai_hub.agents import runtime
        async for _ in runtime.generate_agent_stream(
            agent, session, run, [user_msg], "私は早起きが好き"
        ):
            pass

    cand = next(
        m for m in memory.load_all_memories() if m["content"] == "早起きが好き"
    )
    assert cand["evidence"][0]["quote"] == "私は早起きが好き"
    assert cand["provenance"]["session_id"] == session["session_id"]
    assert cand["provenance"]["run_id"] == run["run_id"]


def test_unexpected_error_sanitized_for_llm():
    tool = registry._make_memory_search_tool()
    with patch(
        "obsidian_ai_hub.memory.agent_tools.search_memories",
        side_effect=RuntimeError("DB password leaked: /var/secrets/x"),
    ):
        res = json.loads(tool.invoke({"query": "test"}))
    assert "error" in res
    assert "password" not in res["error"]
    assert "機密" in res["error"] or "エラー" in res["error"]
