from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

from obsidian_ai_hub.hitl import store as hitl_store
from obsidian_ai_hub.memory import context as memory_context_mod
from obsidian_ai_hub.planner import context, store, suggest
from obsidian_ai_hub.utils import config, reader as reader_mod


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


def test_build_planner_context_pack_degrades_gracefully():
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    with (
        patch.object(reader_mod, "get_daily_note_content", side_effect=boom),
        patch.object(memory_context_mod, "compile_context", side_effect=boom),
    ):
        pack = context.build_planner_context_pack()

    assert isinstance(pack, str)
    assert "## 直近のDaily Note" not in pack


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
        start_time="2026-08-26T10:00:00",
    )
    store.reject_proposal(rec["proposal_id"], reason="done", comment="先週済んだ")

    text = context.build_existing_proposals_block()

    assert "done" in text
    assert "先週済んだ" in text


def test_generate_proposals_creates_and_persists_candidates():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "歯科検診",
                    "start_time": "2026-08-26T10:00:00",
                    "end_time": "2026-08-26T10:30:00",
                    "location": "駅前クリニック",
                    "rationale": "最近のノートに予約希望があったため",
                },
                {
                    "kind": "reminder",
                    "title": "本を返却する",
                    "due_date": "2026-08-20",
                    "rationale": "貸出期限が近いため",
                },
            ]
        },
        ensure_ascii=False,
    )

    def fake_llm(*, provider, model, prompt, temperature, max_tokens):
        assert provider == config.AI_PLANNER_PROVIDER
        assert model == config.AI_PLANNER_MODEL
        assert "MARKER_CONTEXT_PACK" in prompt
        return llm_response

    with (
        patch.object(
            suggest.context,
            "build_planner_context_pack",
            return_value="MARKER_CONTEXT_PACK",
        ),
        patch.object(
            suggest.llm_client, "generate_llm_response", side_effect=fake_llm
        ),
    ):
        created = suggest.generate_proposals()

    assert len(created) == 2
    assert {p["kind"] for p in created} == {"calendar", "reminder"}
    for p in created:
        fetched = store.get_proposal(p["proposal_id"])
        assert fetched["status"] == "proposed"
        assert fetched["rationale"]


def test_generate_proposals_skips_duplicate_active_proposal():
    store.create_proposal(
        kind="calendar",
        title="歯科検診",
        rationale="元の根拠",
        generation_source="daily_06:00",
        start_time="2026-08-26T10:00:00",
    )
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "歯科検診",
                    "start_time": "2026-08-26T10:00:00",
                    "rationale": "重複",
                }
            ]
        }
    )

    with patch.object(
        suggest.llm_client, "generate_llm_response", return_value=llm_response
    ):
        created = suggest.generate_proposals()

    assert created == []
    assert len(store.list_proposals(status="proposed")) == 1


def test_generate_proposals_skips_invalid_candidates():
    llm_response = json.dumps(
        {
            "candidates": [
                {"kind": "bogus", "title": "x", "rationale": "r"},
                {"kind": "calendar", "title": "x", "rationale": ""},
                {"kind": "calendar", "title": "x", "rationale": "r", "start_time": "not-a-date"},
                {"kind": "reminder", "title": "x", "rationale": "r", "due_date": "2026-13-99"},
            ]
        }
    )

    with patch.object(
        suggest.llm_client, "generate_llm_response", return_value=llm_response
    ):
        created = suggest.generate_proposals()

    assert created == []
    assert len(store.list_proposals(status="proposed")) == 0


def test_generate_proposals_returns_empty_on_malformed_llm():
    with patch.object(
        suggest.llm_client, "generate_llm_response", return_value="sorry, no JSON here"
    ):
        created = suggest.generate_proposals()

    assert created == []


def test_generate_proposals_skips_candidate_with_end_before_start():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "逆転予定",
                    "start_time": "2026-08-26T12:00:00",
                    "end_time": "2026-08-26T09:00:00",
                    "rationale": "終了が開始より前",
                }
            ]
        }
    )

    with patch.object(
        suggest.llm_client, "generate_llm_response", return_value=llm_response
    ):
        created = suggest.generate_proposals()

    assert created == []
    assert len(store.list_proposals(status="proposed")) == 0


def test_generate_proposals_accepts_source_label():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "手動生成の予定",
                    "start_time": "2026-08-26T10:00:00",
                    "rationale": "手動生成",
                }
            ]
        }
    )

    with patch.object(
        suggest.llm_client, "generate_llm_response", return_value=llm_response
    ):
        created = suggest.generate_proposals(source="manual")

    assert len(created) == 1
    fetched = store.get_proposal(created[0]["proposal_id"])
    assert fetched["generation_source"] == "manual"


def test_main_notifies_line_with_generated_proposals():
    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "calendar",
                    "title": "歯科検診",
                    "start_time": "2026-08-26T10:00:00",
                    "rationale": "根拠",
                }
            ]
        }
    )
    with (
        patch.object(
            suggest.llm_client, "generate_llm_response", return_value=llm_response
        ),
        patch(
            "obsidian_ai_hub.line_notification.planner.notify_planner_summary",
            return_value=True,
        ) as mock_notify,
    ):
        proposals = suggest.main()

    assert len(proposals) == 1
    mock_notify.assert_called_once_with(proposals)
