from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

from obsidian_ai_hub.activity import store as activity_store_mod
from obsidian_ai_hub.hitl import store as hitl_store
from obsidian_ai_hub.memory import context as memory_context_mod
from obsidian_ai_hub.planner import context, store, suggest
from obsidian_ai_hub.research import db as research_db_mod
from obsidian_ai_hub.summary import project_utils as project_utils_mod
from obsidian_ai_hub.summary import store as summary_store_mod
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


def test_build_planner_context_pack_composes_all_sources():
    with (
        patch.object(
            reader_mod, "get_daily_note_content", return_value="メモ本文の内容"
        ),
        patch.object(
            summary_store_mod,
            "get_summary_by_period",
            side_effect=lambda pt, pk: (
                {"summary": f"サマリ {pk}"} if pt == "day" else {"summary": "週次サマリ"}
            ),
        ),
        patch.object(
            activity_store_mod,
            "get_recent_activities",
            return_value=[
                {
                    "activity_date": "2026-08-18",
                    "summary": "作業ログ",
                    "category": "開発",
                    "keywords": ["a"],
                }
            ],
        ),
        patch.object(
            research_db_mod, "list_themes", return_value=[{"theme": "テーマ1"}]
        ),
        patch.object(research_db_mod, "list_theme_feedback", return_value=[]),
        patch.object(
            project_utils_mod,
            "get_active_projects_for_prompt",
            return_value=[{"display_name": "プロジェクトA", "goal": "ゴール"}],
        ),
        patch.object(
            memory_context_mod,
            "compile_context",
            return_value={"context": "## 根拠付き参考情報（長期記憶）\n- 記憶"},
        ),
    ):
        pack = context.build_planner_context_pack()

    assert "## 直近のDaily Note" in pack
    assert "メモ本文" in pack
    assert "## サマリ" in pack
    assert "週次サマリ" in pack
    assert "## アクティビティ" in pack
    assert "作業ログ" in pack
    assert "## リサーチ" in pack
    assert "テーマ1" in pack
    assert "## アクティブプロジェクト" in pack
    assert "プロジェクトA" in pack
    assert "## 根拠付き参考情報（長期記憶）" in pack


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


def test_build_authoritative_schedule_block_includes_apple_and_recurring():
    reference_date = date(2026, 8, 20)
    with (
        patch.object(
            context.apple,
            "get_external_data",
            return_value={
                "calendar_events": [
                    {
                        "title": "顧客ミーティング",
                        "start": "2026-08-21T09:00:00+09:00",
                        "end": "2026-08-21T10:00:00+09:00",
                        "all_day": False,
                    },
                    {
                        "title": "休暇",
                        "start": "2026-08-22T00:00:00+09:00",
                        "end": "2026-08-22T00:00:00+09:00",
                        "all_day": True,
                    },
                ],
                "reminders": [{"title": "本を返す", "due": "2026-08-23"}],
                "error": None,
            },
        ) as mock_external_data,
        patch.object(
            context.recurring,
            "expand_recurring",
            return_value=[
                {
                    "title": "月次処理",
                    "date": date(2026, 8, 25),
                    "kind": "task",
                }
            ],
        ) as mock_expand_recurring,
    ):
        block = context._build_authoritative_schedule_block(reference_date)

    expected_end_date = date(2026, 9, 18)
    mock_external_data.assert_called_once_with(reference_date, expected_end_date)
    mock_expand_recurring.assert_called_once_with(reference_date, expected_end_date)
    assert "2026-08-20〜2026-09-18" in block
    assert "### Apple Calendar" in block
    assert "2026-08-21T09:00:00+09:00〜2026-08-21T10:00:00+09:00" in block
    assert "休暇" in block
    assert "終日" in block
    assert "### Apple Reminders" in block
    assert "2026-08-23 | 本を返す" in block
    assert "### CONFIG 定期予定" in block
    assert "2026-08-25 / タスク | 月次処理" in block


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


def test_build_llm_prompt_instructs_schedule_deduplication_and_conflict_avoidance():
    with patch.object(
        suggest.context,
        "build_planner_context_pack",
        return_value="## 今後30日間の正本スケジュール\n- 既存予定",
    ):
        prompt_text = suggest._build_llm_prompt()

    assert "正本スケジュール" in prompt_text
    assert "実質同じ内容の候補は出さない" in prompt_text
    assert "重複しない時刻" in prompt_text


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


def test_build_existing_proposals_block_lists_promoted_and_rejected():
    promoted = store.create_proposal(
        kind="calendar",
        title="歯科検診",
        rationale="根拠",
        generation_source="daily_06:00",
        start_time="2026-08-26T10:00:00",
    )
    rejected = store.create_proposal(
        kind="reminder",
        title="本を返す",
        rationale="根拠",
        generation_source="daily_06:00",
        due_date="2026-08-20",
    )
    store.transition_status(promoted["proposal_id"], to_status="promoted")
    store.transition_status(rejected["proposal_id"], to_status="rejected")

    text = context.build_existing_proposals_block()

    assert "[promoted]" in text
    assert "[rejected]" in text
    assert "歯科検診" in text
    assert "本を返す" in text


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
        assert "最大10件" in prompt
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
