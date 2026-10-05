# ruff: noqa: E402
import sys
from unittest.mock import MagicMock, patch

# Mock macOS-specific modules before importing obsidian_ai_hub
mock_modules = {
    "EventKit": MagicMock(),
    "AppKit": MagicMock(),
    "objc": MagicMock(),
    "Foundation": MagicMock(),
    "ApplicationServices": MagicMock(),
    "atomacos": MagicMock(),
    "Quartz": MagicMock(),
    "Vision": MagicMock(),
    "Cocoa": MagicMock(),
}
for name, m in mock_modules.items():
    sys.modules[name] = m

import json

import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub.memory.dedup import (
    assess_and_persist_candidate,
    perform_dedup_assessment_llm,
)
from obsidian_ai_hub.memory.models import compute_memory_fingerprint
from obsidian_ai_hub.utils import config


@pytest.fixture
def clean_memory_env(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault"
    vault_path.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "VAULT_PATH", vault_path)

    activity_dir = vault_path / "activity"
    activity_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "ACTIVITY_PATH", activity_dir)

    db_path = tmp_path / "memory.sqlite3"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_path)

    return vault_path


def _make_approved(mid="mem_target_dd", content="承認済みの内容", key="key-dd"):
    return {
        "schema_version": 1,
        "memory_id": mid,
        "status": "approved",
        "kind": "preference",
        "memory_key": key,
        "content": content,
        "topics": [],
        "tags": [],
        "evidence": [],
        "valid_from": "2026-08-01",
        "created_at": "2026-08-01T10:00:00+09:00",
        "updated_at": "2026-08-01T10:00:00+09:00",
    }


def _make_candidate(cid="cand_dd_1", target_id="mem_target_dd", key="key-dd"):
    return {
        "schema_version": 1,
        "memory_id": cid,
        "status": "candidate",
        "kind": "preference",
        "memory_key": key,
        "content": "候補の内容",
        "topics": [],
        "tags": [],
        "evidence": [],
        "valid_from": "2026-08-01",
        "dedup_suggestions": [{"target_memory_id": target_id, "relation": "duplicate"}],
        "dedup_assessment": None,
        "created_at": "2026-08-01T10:00:00+09:00",
        "updated_at": "2026-08-01T10:00:00+09:00",
    }


def test_failed_assessment_carries_reassessment_flag():
    target = _make_approved()
    cand = _make_candidate()

    with patch(
        "obsidian_ai_hub.utils.llm_client.generate_llm_response",
        side_effect=ValueError("boom"),
    ):
        perform_dedup_assessment_llm([cand], [target])

    assessment = cand["dedup_assessment"]
    assert assessment["decision"] == "failed"
    assert assessment["failure_kind"] == "request_failed"
    assert assessment["reassessment_required"] is True


def test_assess_and_persist_candidate_saves_merge_assessment(clean_memory_env):
    target = _make_approved()
    cand = _make_candidate()
    memory.save_all_memories([target, cand])

    llm_response = json.dumps([
        {
            "candidate_id": "cand_dd_1",
            "decision": "merge",
            "target_memory_id": "mem_target_dd",
            "integrated_content": "統合された内容",
            "reason": "重複のため統合",
        }
    ])
    with patch(
        "obsidian_ai_hub.utils.llm_client.generate_llm_response",
        return_value=llm_response,
    ):
        result = assess_and_persist_candidate("cand_dd_1")

    assert result["found"] is True
    assert result["assessment"]["decision"] == "merge"

    stored = memory.get_memory("cand_dd_1")
    assert stored["dedup_assessment"]["decision"] == "merge"
    assert stored["dedup_assessment"]["target_memory_id"] == "mem_target_dd"
    assert stored["dedup_assessment"]["target_fingerprint"] == compute_memory_fingerprint(
        memory.get_memory("mem_target_dd")
    )
    assert stored["dedup_assessment"].get("reassessment_required") is False

    events = memory.get_memory_events("cand_dd_1")
    assert any(e["event_type"] == "dedup_assessed" for e in events)


def test_assess_and_persist_candidate_rejects_non_candidate(clean_memory_env):
    memory.save_all_memories([_make_approved()])

    with pytest.raises(ValueError, match="not found"):
        assess_and_persist_candidate("mem_missing")

    with pytest.raises(ValueError, match="not a candidate"):
        assess_and_persist_candidate("mem_target_dd")


def test_assess_and_persist_candidate_persists_failed_assessment(clean_memory_env):
    memory.save_all_memories([_make_approved(), _make_candidate()])

    with patch(
        "obsidian_ai_hub.utils.llm_client.generate_llm_response",
        side_effect=ValueError("boom"),
    ):
        result = assess_and_persist_candidate("cand_dd_1")

    assert result["assessment"]["decision"] == "failed"
    stored = memory.get_memory("cand_dd_1")
    assert stored["dedup_assessment"]["decision"] == "failed"
    assert stored["dedup_assessment"]["reassessment_required"] is True
