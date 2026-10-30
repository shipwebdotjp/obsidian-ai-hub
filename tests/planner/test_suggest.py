from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

from obsidian_ai_hub.hitl import store as hitl_store
from obsidian_ai_hub.memory import context as memory_context_mod
from obsidian_ai_hub.planner import context, notes, store, suggest
from obsidian_ai_hub.utils import config


def _pending_run(run_id: str, handler: str, title: str) -> dict:
    return {
        "run_id": run_id,
        "handler": handler,
        "status": "pending_user",
        "checkpoint": "",
        "active_question_set_id": None,
        "lease_owner": None,
        "lease_expires_at": None,
        "retry_count": 0,
        "error_message": None,
        "created_at": "2026-08-19T00:00:00+00:00",
        "updated_at": "2026-08-19T00:00:00+00:00",
        "title": title,
        "description": "",
        "display_type": "approval",
    }


def _evidence_lines() -> list[notes.EvidenceLine]:
    return [
        notes.EvidenceLine(ref="E1", date=date(2026, 10, 29), text="本を図書館に返す（期限10/31）"),
        notes.EvidenceLine(ref="E2", date=date(2026, 10, 29), text="歯科検診の予約を入れる"),
    ]


def test_evidence_block_is_the_only_proposal_source():
    pack = context.build_planner_context_pack(_evidence_lines())

    assert "[E1] 本を図書館に返す（期限10/31）" in pack
    assert "[E2] 歯科検診の予約を入れる" in pack
    for removed in ("## アクティビティ", "## アクティブプロジェクト", "## リサーチ", "## サマリ"):
        assert removed not in pack


def test_build_planner_context_pack_degrades_gracefully():
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    with patch.object(memory_context_mod, "compile_context", side_effect=boom):
        pack = context.build_planner_context_pack(_evidence_lines())

    assert isinstance(pack, str)
    assert "[E1]" in pack
    assert "## 長期メモリ" not in pack


def test_build_authoritative_schedule_block_keeps_recurring_when_apple_fails():
    reference_date = date(2026, 8, 20)
    with (
        patch.object(context.apple, "get_external_data", side_effect=RuntimeError("boom")),
        patch.object(
            context.recurring,
            "expand_recurring",
            return_value=[
                {
                    "title": "定例会",
                    "date": date(2026, 8, 21),
                    "kind": "event",
                }
            ],
        ),
    ):
        block = context._build_authoritative_schedule_block(reference_date)

    assert "Apple Calendar" not in block
    assert "Apple Reminders" not in block
    assert "2026-08-21 / 予定 | 定例会" in block


def test_build_excluded_inbox_items_lists_pending_calendar_reminder():
    hitl_store.upsert_run(
        _pending_run("run_cal", "calendar.add_approved_event", "歯科検診")
    )
    hitl_store.upsert_run(
        _pending_run("run_rem", "reminders.add_approved_reminder", "本を返す")
    )
    hitl_store.upsert_run(
        _pending_run("run_mem", "memory.interview", "記憶インタビュー")
    )

    text = context.build_excluded_inbox_items()

    assert "歯科検診" in text
    assert "本を返す" in text
    assert "記憶インタビュー" not in text


def test_build_existing_proposals_block_includes_rejection_reason():
    rec = store.create_proposal(
        kind="calendar",
        title="歯科検診",
        rationale="根拠",
        generation_source="daily_06:00",
        start_time="2099-08-26T10:00:00",
    )
    store.reject_proposal(rec["proposal_id"], reason="done", comment="先週済んだ")

    text = context.build_existing_proposals_block()

    assert "done" in text
    assert "先週済んだ" in text


def _generate(llm_response: str, *, source: str = suggest.GENERATION_SOURCE):
    with (
        patch.object(
            suggest.notes, "collect_citable_lines", return_value=_evidence_lines()
        ),
        patch.object(
            suggest.context,
            "build_planner_context_pack",
            return_value="MARKER_CONTEXT_PACK",
        ),
        patch.object(
            suggest.llm_client, "generate_llm_response", return_value=llm_response
        ) as mock_llm,
    ):
        result = suggest.run_generation(source)
    return result, mock_llm


def test_generate_proposals_creates_and_persists_candidates():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "歯科検診",
                    "start_time": "2099-08-26T10:00:00",
                    "end_time": "2099-08-26T10:30:00",
                    "location": "駅前クリニック",
                    "rationale": "E2 に予約することが書かれているため",
                    "evidence": {"ref": "E2"},
                },
                {
                    "kind": "reminder",
                    "title": "本を返却する",
                    "due_date": "2099-08-20",
                    "rationale": "E1 に返却期限が書かれているため",
                    "evidence": {"ref": "E1"},
                },
            ]
        },
        ensure_ascii=False,
    )

    result, _ = _generate(llm_response)

    assert len(result.created) == 2
    assert {p["kind"] for p in result.created} == {"calendar", "reminder"}
    for p in result.created:
        fetched = store.get_proposal(p["proposal_id"])
        assert fetched["status"] == "proposed"
        assert fetched["rationale"]


def test_generate_proposals_uses_configured_model():
    llm_response = json.dumps({"candidates": []})

    with (
        patch.object(
            suggest.notes, "collect_citable_lines", return_value=_evidence_lines()
        ),
        patch.object(
            suggest.context,
            "build_planner_context_pack",
            return_value="MARKER_CONTEXT_PACK",
        ),
        patch.object(
            suggest.llm_client, "generate_llm_response", return_value=llm_response
        ) as mock_llm,
    ):
        suggest.run_generation()

    kwargs = mock_llm.call_args.kwargs
    assert kwargs["provider"] == config.AI_PLANNER_PROVIDER
    assert kwargs["model"] == config.AI_PLANNER_MODEL
    assert "MARKER_CONTEXT_PACK" in kwargs["prompt"]


def test_zero_candidates_is_a_normal_success():
    with (
        patch.object(
            suggest.notes, "collect_citable_lines", return_value=_evidence_lines()
        ),
        patch.object(
            suggest.context,
            "build_planner_context_pack",
            return_value="MARKER_CONTEXT_PACK",
        ),
        patch.object(
            suggest.llm_client,
            "generate_llm_response",
            return_value='{"candidates": []}',
        ) as mock_llm,
        patch(
            "obsidian_ai_hub.line_notification.planner.notify_planner_summary",
            return_value=True,
        ) as mock_notify,
    ):
        result = suggest.run_generation()

    assert result.created == []
    assert result.skipped is None
    assert result.dropped == {}
    assert mock_llm.call_count == 1
    mock_notify.assert_not_called()
    assert store.list_proposals(status="proposed") == []


def test_no_evidence_lines_skips_the_llm_call():
    with (
        patch.object(suggest.notes, "collect_citable_lines", return_value=[]),
        patch.object(
            suggest.llm_client, "generate_llm_response"
        ) as mock_llm,
    ):
        result = suggest.run_generation()

    assert result.skipped == "no_evidence_lines"
    assert result.created == []
    mock_llm.assert_not_called()


def test_unknown_evidence_ref_is_dropped_without_retry():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "reminder",
                    "title": "本を返却する",
                    "due_date": "2099-08-20",
                    "rationale": "根拠",
                    "evidence": {"ref": "E99"},
                }
            ]
        }
    )

    result, mock_llm = _generate(llm_response)

    assert result.created == []
    assert result.dropped == {suggest.DROP_REF_NOT_FOUND: 1}
    assert mock_llm.call_count == 1
    assert store.list_proposals(status="proposed") == []


def test_missing_evidence_is_dropped():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "reminder",
                    "title": "本を返却する",
                    "due_date": "2099-08-20",
                    "rationale": "根拠",
                }
            ]
        }
    )

    result, _ = _generate(llm_response)

    assert result.created == []
    assert result.dropped == {suggest.DROP_EVIDENCE_MISSING: 1}


def test_quoted_evidence_is_resolved_as_a_rescue_path():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "reminder",
                    "title": "本を返却する",
                    "due_date": "2099-08-20",
                    "rationale": "E1 に返却期限が書かれているため",
                    "evidence": {"quote": "本を図書館に返す"},
                }
            ]
        },
        ensure_ascii=False,
    )

    result, _ = _generate(llm_response)

    assert len(result.created) == 1


def test_generate_proposals_skips_duplicate_active_proposal():
    store.create_proposal(
        kind="calendar",
        title="歯科検診",
        rationale="元の根拠",
        generation_source="daily_06:00",
        start_time="2099-08-26T10:00:00",
    )
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "歯科検診",
                    "start_time": "2099-08-26T10:00:00",
                    "rationale": "重複",
                    "evidence": {"ref": "E2"},
                }
            ]
        }
    )

    result, _ = _generate(llm_response)

    assert result.created == []
    assert result.dropped == {suggest.DROP_DUPLICATE_ACTIVE: 1}
    assert len(store.list_proposals(status="proposed")) == 1


def test_generate_proposals_skips_invalid_candidates():
    llm_response = json.dumps(
        {
            "candidates": [
                {"kind": "bogus", "title": "x", "rationale": "r", "evidence": {"ref": "E1"}},
                {
                    "kind": "calendar",
                    "title": "x",
                    "rationale": "",
                    "evidence": {"ref": "E1"},
                },
                {
                    "kind": "calendar",
                    "title": "x",
                    "rationale": "r",
                    "start_time": "not-a-date",
                    "evidence": {"ref": "E1"},
                },
                {
                    "kind": "reminder",
                    "title": "x",
                    "rationale": "r",
                    "due_date": "2026-13-99",
                    "evidence": {"ref": "E1"},
                },
            ]
        }
    )

    result, _ = _generate(llm_response)

    assert result.created == []
    assert sum(result.dropped.values()) == 4
    assert len(store.list_proposals(status="proposed")) == 0


def test_generate_proposals_returns_empty_on_malformed_llm():
    with patch.object(
        suggest.llm_client, "generate_llm_response", return_value="sorry, no JSON here"
    ) as mock_llm, patch.object(
        suggest.notes, "collect_citable_lines", return_value=_evidence_lines()
    ), patch.object(
        suggest.context, "build_planner_context_pack", return_value="CTX"
    ):
        created = suggest.generate_proposals()

    assert created == []
    assert mock_llm.call_count == 2


def test_generate_proposals_skips_candidate_with_end_before_start():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "逆転予定",
                    "start_time": "2099-08-26T12:00:00",
                    "end_time": "2099-08-26T09:00:00",
                    "rationale": "終了が開始より前",
                    "evidence": {"ref": "E1"},
                }
            ]
        }
    )

    result, _ = _generate(llm_response)

    assert result.created == []
    assert result.dropped == {suggest.DROP_BAD_DATETIME: 1}
    assert len(store.list_proposals(status="proposed")) == 0


def test_generate_proposals_accepts_source_label():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "手動生成の予定",
                    "start_time": "2099-08-26T10:00:00",
                    "rationale": "手動生成",
                    "evidence": {"ref": "E2"},
                }
            ]
        }
    )

    result, _ = _generate(llm_response, source="manual")

    assert len(result.created) == 1
    fetched = store.get_proposal(result.created[0]["proposal_id"])
    assert fetched["generation_source"] == "manual"


def test_generation_expires_stale_proposals_first():
    stale = store.create_proposal(
        kind="calendar",
        title="過去の予定",
        rationale="根拠",
        generation_source="daily_06:00",
        start_time="2020-01-01T10:00:00",
    )

    _generate(json.dumps({"candidates": []}))

    assert store.get_proposal(stale["proposal_id"])["status"] == "expired"


def test_main_notifies_line_with_generated_proposals():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "歯科検診",
                    "start_time": "2099-08-26T10:00:00",
                    "rationale": "根拠",
                    "evidence": {"ref": "E1"},
                }
            ]
        }
    )
    with (
        patch.object(
            suggest.notes, "collect_citable_lines", return_value=_evidence_lines()
        ),
        patch.object(
            suggest.context, "build_planner_context_pack", return_value="CTX"
        ),
        patch.object(
            suggest.llm_client, "generate_llm_response", return_value=llm_response
        ),
        patch(
            "obsidian_ai_hub.line_notification.planner.notify_planner_summary",
            return_value=True,
        ) as mock_notify,
    ):
        summary = suggest.main()

    assert summary["generated"] == 1
    assert summary["skipped"] is None
    mock_notify.assert_called_once()


def test_dry_run_reports_candidates_without_persisting():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "歯科検診",
                    "start_time": "2099-08-26T10:00:00",
                    "rationale": "根拠",
                    "evidence": {"ref": "E2"},
                },
                {
                    "kind": "reminder",
                    "title": "本を返却する",
                    "due_date": "2099-08-20",
                    "rationale": "根拠",
                    "evidence": {"ref": "E99"},
                },
            ]
        }
    )

    with (
        patch.object(
            suggest.notes, "collect_citable_lines", return_value=_evidence_lines()
        ),
        patch.object(
            suggest.context, "build_planner_context_pack", return_value="CTX"
        ),
        patch.object(
            suggest.llm_client, "generate_llm_response", return_value=llm_response
        ),
        patch.object(suggest.store, "expire_stale_proposals") as mock_expire,
    ):
        result = suggest.run_generation(dry_run=True)

    assert len(result.candidates) == 1
    assert result.candidates[0]["evidence_ref"] == "E2"
    assert result.candidates[0]["evidence_text"] == "歯科検診の予約を入れる"
    assert result.dropped == {suggest.DROP_REF_NOT_FOUND: 1}
    assert store.list_proposals(status="proposed") == []
    mock_expire.assert_not_called()


def test_bracketed_evidence_ref_is_accepted():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "reminder",
                    "title": "本を返却する",
                    "due_date": "2099-08-20",
                    "rationale": "根拠",
                    "evidence": {"ref": "[E1]"},
                }
            ]
        }
    )

    result, _ = _generate(llm_response)

    assert len(result.created) == 1


def test_non_string_datetime_is_dropped_without_aborting_the_batch():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "reminder",
                    "title": "数値日付",
                    "due_date": 20260820,
                    "rationale": "根拠",
                    "evidence": {"ref": "E1"},
                },
                {
                    "kind": "reminder",
                    "title": "正常な候補",
                    "due_date": "2099-08-20",
                    "rationale": "根拠",
                    "evidence": {"ref": "E1"},
                },
            ]
        }
    )

    result, _ = _generate(llm_response)

    assert [p["title"] for p in result.created] == ["正常な候補"]
    assert result.dropped == {suggest.DROP_BAD_DATETIME: 1}


def test_mixed_timezone_bounds_are_dropped_instead_of_crashing():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "タイムゾーン混在",
                    "start_time": "2099-08-26T10:00:00",
                    "end_time": "2099-08-26T10:30:00+09:00",
                    "rationale": "根拠",
                    "evidence": {"ref": "E1"},
                }
            ]
        }
    )

    result, _ = _generate(llm_response)

    assert result.created == []
    assert result.dropped == {suggest.DROP_BAD_DATETIME: 1}


def test_empty_datetime_string_is_treated_as_absent():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "reminder",
                    "title": "日付なしリマインダー",
                    "due_date": "",
                    "rationale": "根拠",
                    "evidence": {"ref": "E1"},
                },
                {
                    "kind": "calendar",
                    "title": "終了時刻なし予定",
                    "start_time": "2099-08-26T10:00:00",
                    "end_time": "",
                    "rationale": "根拠",
                    "evidence": {"ref": "E1"},
                },
            ]
        }
    )

    result, _ = _generate(llm_response)

    assert len(result.created) == 2
    assert result.dropped == {}


def test_past_dated_candidates_are_dropped():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "reminder",
                    "title": "過去のリマインダー",
                    "due_date": "2020-01-01",
                    "rationale": "根拠",
                    "evidence": {"ref": "E1"},
                },
                {
                    "kind": "calendar",
                    "title": "過去の予定",
                    "start_time": "2020-01-01T10:00:00",
                    "rationale": "根拠",
                    "evidence": {"ref": "E1"},
                },
            ]
        }
    )

    result, _ = _generate(llm_response)

    assert result.created == []
    assert result.dropped == {suggest.DROP_PAST_ANCHOR: 2}
    assert store.list_proposals(status="proposed") == []


def test_reminder_without_due_date_is_still_allowed():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "reminder",
                    "title": "日付未定の用件",
                    "rationale": "根拠",
                    "evidence": {"ref": "E1"},
                }
            ]
        }
    )

    result, _ = _generate(llm_response)

    assert len(result.created) == 1
    assert result.created[0]["due_date"] is None
