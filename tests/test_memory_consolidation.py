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
from obsidian_ai_hub.memory.consolidation import consolidate_candidate_proposals
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


def _make_mem(
    memory_id: str,
    status: str = "candidate",
    content: str = "内容",
    scope: str = "user",
    target_id: str = None,
    decision: str = None,
) -> dict:
    target_fp = None
    if target_id and decision in ("merge", "supersede"):
        t_mem = memory.get_memory(target_id)
        if t_mem:
            target_fp = compute_memory_fingerprint(t_mem)

    dedup_assessment = None
    if decision:
        dedup_assessment = {
            "decision": decision,
            "target_memory_id": target_id,
            "target_fingerprint": target_fp,
            "reason": "テスト用重複判定",
        }
        if decision == "merge":
            dedup_assessment["integrated_content"] = f"{content} + 統合本文"

    return {
        "schema_version": 1,
        "memory_id": memory_id,
        "status": status,
        "scope": scope,
        "kind": "preference",
        "memory_key": f"key-{memory_id}",
        "content": content,
        "topics": ["健康・医療・フィットネス"],
        "tags": ["test"],
        "evidence": [
            {"path": f"note_{memory_id}.md", "quote": f"引用 {memory_id}", "observed_at": "2026-08-01"}
        ],
        "valid_from": "2026-08-01",
        "valid_until": None,
        "review_due_at": None,
        "stability": "tentative",
        "sensitivity": "personal",
        "extraction_confidence": 0.9,
        "supersedes": None,
        "contradicts": [],
        "dedup_suggestions": [
            {"target_memory_id": target_id, "relation": decision, "score": 0.95}
        ]
        if target_id
        else [],
        "dedup_assessment": dedup_assessment,
        "provenance": {"extraction_method": "test"},
        "created_at": "2026-08-01T10:00:00+09:00",
        "updated_at": "2026-08-01T10:00:00+09:00",
        "reviewed_by": None,
        "reviewed_at": None,
    }


def test_consolidate_candidate_proposals_happy_path(clean_memory_env):
    target = _make_mem("mem_target_1", status="approved", content="毎朝ストレッチをする")
    memory.save_all_memories([target])

    cand1 = _make_mem("cand_1", status="candidate", content="毎朝10分間ストレッチをする", target_id="mem_target_1", decision="merge")
    cand2 = _make_mem("cand_2", status="candidate", content="ストレッチ後に白湯を飲む", target_id="mem_target_1", decision="merge")
    cand1["tags"] = ["stretch", "morning"]
    cand2["tags"] = ["stretch", "water"]
    memory.save_all_memories([target, cand1, cand2])

    llm_mock_response = json.dumps({
        "decision": "merge",
        "target_memory_id": "mem_target_1",
        "kind": "preference",
        "memory_key": "morning-routine",
        "content": "毎朝10分間ストレッチをして白湯を飲む",
        "integrated_content": "毎朝10分間ストレッチをし、その後に白湯を飲む",
        "reason": "朝のルーティンに関する2件の候補を正本へ統合",
        "topics": ["健康・医療・フィットネス"],
        "tags": ["stretch", "morning", "water"],
    })

    with patch("obsidian_ai_hub.utils.llm_client.generate_llm_response", return_value=llm_mock_response):
        consolidated = consolidate_candidate_proposals()

    assert len(consolidated) == 1
    cons = consolidated[0]
    assert cons["status"] == "candidate"
    assert cons["content"] == "毎朝10分間ストレッチをし、その後に白湯を飲む"
    assert cons["dedup_assessment"]["decision"] == "merge"
    assert cons["dedup_assessment"]["target_memory_id"] == "mem_target_1"
    assert cons["provenance"]["consolidation"]["source_candidate_ids"] == ["cand_1", "cand_2"]
    assert set(cons["tags"]) == {"stretch", "morning", "water"}
    assert len(cons["evidence"]) == 2

    # Check that source candidates are system rejected with 'consolidated' event
    updated_cand1 = memory.get_memory("cand_1")
    assert updated_cand1["status"] == "rejected"
    assert updated_cand1["reviewed_by"] == "system"

    updated_cand2 = memory.get_memory("cand_2")
    assert updated_cand2["status"] == "rejected"
    assert updated_cand2["reviewed_by"] == "system"

    events1 = memory.get_memory_events("cand_1")
    assert any(
        e["event_type"] == "consolidated"
        and e["actor"] == "system"
        and e["changes"].get("consolidated_into_memory_id") == cons["memory_id"]
        and e["changes"].get("target_memory_id") == "mem_target_1"
        for e in events1
    )


def test_consolidate_candidate_proposals_single_candidate_guarantee(clean_memory_env):
    target = _make_mem("mem_target_2", status="approved", content="週2回ジョギングする")
    memory.save_all_memories([target])

    cand1 = _make_mem("cand_3", status="candidate", content="火曜と木曜に3kmジョギングする", target_id="mem_target_2", decision="merge")
    cand2 = _make_mem("cand_4", status="candidate", content="ジョギング後にプロテインを飲む", target_id="mem_target_2", decision="merge")
    memory.save_all_memories([target, cand1, cand2])

    llm_mock = json.dumps({
        "decision": "merge",
        "target_memory_id": "mem_target_2",
        "integrated_content": "火曜と木曜に3kmジョギングし、直後にプロテインを飲む",
        "reason": "ジョギングとプロテインの統合",
    })

    with patch("obsidian_ai_hub.utils.llm_client.generate_llm_response", return_value=llm_mock):
        consolidate_candidate_proposals()

    all_mems = memory.load_all_memories()
    active_candidates_for_target = [
        m for m in all_mems
        if m["status"] == "candidate"
        and m.get("dedup_assessment", {}).get("target_memory_id") == "mem_target_2"
    ]
    # Single candidate guarantee: exactly 1 candidate proposal targeting mem_target_2
    assert len(active_candidates_for_target) == 1


def test_consolidate_candidate_proposals_resolve_memory_integration(clean_memory_env):
    target = _make_mem("mem_target_3", status="approved", content="コーヒーはブラックで飲む")
    memory.save_all_memories([target])

    cand1 = _make_mem("cand_5", status="candidate", content="毎朝深煎りブラックコーヒーを飲む", target_id="mem_target_3", decision="merge")
    cand2 = _make_mem("cand_6", status="candidate", content="コーヒーは1日2杯までにする", target_id="mem_target_3", decision="merge")
    memory.save_all_memories([target, cand1, cand2])

    llm_mock = json.dumps({
        "decision": "merge",
        "target_memory_id": "mem_target_3",
        "integrated_content": "毎朝深煎りブラックコーヒーを飲み、1日2杯までに抑える",
        "reason": "コーヒーの好みと摂取量の統合",
    })

    with patch("obsidian_ai_hub.utils.llm_client.generate_llm_response", return_value=llm_mock):
        consolidated = consolidate_candidate_proposals()

    cons_id = consolidated[0]["memory_id"]

    # Approve consolidated proposal via resolve_memory
    _, updated_target = memory.resolve_memory(
        cons_id,
        "merge_existing",
        "mem_target_3",
        integrated_content="毎朝深煎りブラックコーヒーを飲み、1日2杯までに抑える",
    )
    assert updated_target["content"] == "毎朝深煎りブラックコーヒーを飲み、1日2杯までに抑える"
    assert updated_target["status"] == "approved"

    # Verify no active candidates targeting mem_target_3 remain
    all_mems = memory.load_all_memories()
    active_candidates = [
        m for m in all_mems
        if m["status"] == "candidate"
        and m.get("dedup_assessment", {}).get("target_memory_id") == "mem_target_3"
    ]
    assert len(active_candidates) == 0


def test_consolidate_candidate_proposals_llm_failure_fallback(clean_memory_env):
    target = _make_mem("mem_target_fail", status="approved", content="英会話の勉強")
    memory.save_all_memories([target])

    cand1 = _make_mem("cand_f1", status="candidate", content="火曜夜に英会話", target_id="mem_target_fail", decision="merge")
    cand2 = _make_mem("cand_f2", status="candidate", content="オンライン英会話を使用", target_id="mem_target_fail", decision="merge")
    memory.save_all_memories([target, cand1, cand2])

    # LLM throws exception
    with patch("obsidian_ai_hub.utils.llm_client.generate_llm_response", side_effect=ValueError("LLM error")):
        consolidated = consolidate_candidate_proposals()

    assert len(consolidated) == 0
    # Original candidates remain intact
    updated_cand1 = memory.get_memory("cand_f1")
    updated_cand2 = memory.get_memory("cand_f2")
    assert updated_cand1["status"] == "candidate"
    assert updated_cand2["status"] == "candidate"


def test_reconsolidation_with_existing_consolidated_candidate(clean_memory_env):
    target = _make_mem("mem_target_recon", status="approved", content="就寝前読書")
    memory.save_all_memories([target])

    cand1 = _make_mem("cand_r1", status="candidate", content="就寝前に30分読書する", target_id="mem_target_recon", decision="merge")
    cand2 = _make_mem("cand_r2", status="candidate", content="Kindleで小説を読む", target_id="mem_target_recon", decision="merge")
    memory.save_all_memories([target, cand1, cand2])

    llm_mock1 = json.dumps({
        "decision": "merge",
        "target_memory_id": "mem_target_recon",
        "integrated_content": "就寝前にKindleで30分小説を読む",
        "reason": "初回統合",
    })

    with patch("obsidian_ai_hub.utils.llm_client.generate_llm_response", return_value=llm_mock1):
        cons1 = consolidate_candidate_proposals()[0]

    # Now a 3rd candidate arrives
    cand3 = _make_mem("cand_r3", status="candidate", content="就寝前読書は22:30に開始する", target_id="mem_target_recon", decision="merge")
    memory.save_all_memories(memory.load_all_memories() + [cand3])

    llm_mock2 = json.dumps({
        "decision": "merge",
        "target_memory_id": "mem_target_recon",
        "integrated_content": "就寝前の22:30からKindleで30分小説を読む",
        "reason": "2回目再統合",
    })

    with patch("obsidian_ai_hub.utils.llm_client.generate_llm_response", return_value=llm_mock2):
        cons2 = consolidate_candidate_proposals()[0]

    assert cons2["memory_id"] != cons1["memory_id"]
    assert cons2["content"] == "就寝前の22:30からKindleで30分小説を読む"

    # Previous consolidated candidate cons1 is now rejected with 'consolidated' event
    updated_cons1 = memory.get_memory(cons1["memory_id"])
    assert updated_cons1["status"] == "rejected"
    assert updated_cons1["reviewed_by"] == "system"

    # Single active candidate remains for mem_target_recon
    all_mems = memory.load_all_memories()
    active_candidates = [
        m for m in all_mems
        if m["status"] == "candidate"
        and m.get("dedup_assessment", {}).get("target_memory_id") == "mem_target_recon"
    ]
    assert len(active_candidates) == 1
    assert active_candidates[0]["memory_id"] == cons2["memory_id"]


def test_agent_memory_propose_triggers_consolidation(clean_memory_env):
    target = _make_mem("mem_target_agent", status="approved", content="UIはダークモードを好む")
    memory.save_all_memories([target])

    trusted_ctx = {
        "agent_id": "agent-1",
        "session_id": "ses-1",
        "run_id": "run-1",
        "user_message_id": "msg-1",
        "user_content": "ダークモードが好きです",
        "now": "2026-08-01T12:00:00+09:00",
    }

    def set_assessment(cands, approved):
        for c in cands:
            c["dedup_assessment"] = {
                "decision": "merge",
                "target_memory_id": "mem_target_agent",
                "target_fingerprint": compute_memory_fingerprint(target),
                "reason": "ダークモードに関する提案",
            }

    from obsidian_ai_hub.memory.agent_tools import create_memory_candidate

    with patch("obsidian_ai_hub.memory.consolidation.perform_dedup_assessment_llm", side_effect=set_assessment):
        res1 = create_memory_candidate(
            content="Web UIはダークモードを標準にする",
            kind="preference",
            trusted_ctx=trusted_ctx,
        )
        assert res1["status"] == "candidate_created"

        trusted_ctx["user_message_id"] = "msg-2"
        llm_cons_mock = json.dumps({
            "decision": "merge",
            "target_memory_id": "mem_target_agent",
            "integrated_content": "Web UIおよび開発ツールのUIはダークモードを標準にする",
            "reason": "ダークモード設定の統合",
        })
        with patch("obsidian_ai_hub.utils.llm_client.generate_llm_response", return_value=llm_cons_mock):
            res2 = create_memory_candidate(
                content="開発ツールのUIもダークモードを使う",
                kind="preference",
                trusted_ctx=trusted_ctx,
            )
            assert res2["status"] == "candidate_created"

    # Verify that consolidation merged both candidates into 1 consolidated candidate
    all_mems = memory.load_all_memories()
    active_candidates = [
        m for m in all_mems
        if m["status"] == "candidate"
        and (m.get("dedup_assessment") or {}).get("target_memory_id") == "mem_target_agent"
    ]
    assert len(active_candidates) == 1
    assert active_candidates[0]["content"] == "Web UIおよび開発ツールのUIはダークモードを標準にする"
