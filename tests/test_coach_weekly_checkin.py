"""Tests for the weekly check-in HITL flow (coach.weekly_checkin)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from obsidian_ai_hub import hitl
from obsidian_ai_hub.coach import CoachService
from obsidian_ai_hub.coach.store import CoachStore
from obsidian_ai_hub.coach.weekly_checkin import (
    QUESTION_DECISION,
    QUESTION_NEXT_STEP,
    QUESTION_NOTE,
    QUESTION_TARGET_FOCUS,
    _fallback_question,
    apply_weekly_checkin,
    build_checkin_question,
    generate_weekly_checkin,
    get_checkin_week_monday,
    run_id_for_week,
    select_checkin_target,
)
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl.dispatcher import dispatch_runs, register_handler


@pytest.fixture(autouse=True)
def _register_checkin_handler():
    register_handler("coach.apply_weekly_checkin", apply_weekly_checkin)
    yield


def _make_goal_with_focus(reason="成長のため"):
    svc = CoachService()
    goal = svc.create_goal("技術力を磨く", reason, ["週1アウトプット", "毎日15分読書"])
    return svc, goal


def _answer_all(
    run_id,
    note="今週は声をかけられた",
    decision="continue",
    next_step=None,
    target=None,
    conn=None,
):
    """Submit answers in card order: optional first, required last."""
    if next_step is not None:
        hitl.submit_answer(run_id, "initial", QUESTION_NEXT_STEP, next_step, conn)
    if target is not None:
        hitl.submit_answer(run_id, "initial", QUESTION_TARGET_FOCUS, target, conn)
    hitl.submit_answer(run_id, "initial", QUESTION_NOTE, note, conn)
    hitl.submit_answer(run_id, "initial", QUESTION_DECISION, decision, conn)


def test_run_id_is_stable_per_week():
    assert run_id_for_week("2026-10-26") == "coach_checkin_2026-W44"
    assert run_id_for_week("2026-10-26") == run_id_for_week("2026-10-28")
    assert get_checkin_week_monday("2026-10-28") == "2026-10-26"


def test_generate_creates_run_questions_and_notifies_once(
    test_memory_db_path, monkeypatch
):
    _make_goal_with_focus()
    conn = get_db_connection()
    try:
        monkeypatch.setattr(
            "obsidian_ai_hub.coach.weekly_checkin.llm_client.generate_llm_response",
            lambda *a, **kw: "生成された問い文",
        )
        with patch("obsidian_ai_hub.line_notification.notify_hitl_run") as mock_notify:
            run_id = generate_weekly_checkin("2026-10-28")
            assert run_id == "coach_checkin_2026-W44"
            mock_notify.assert_called_once()
            assert mock_notify.call_args.kwargs["run_id"] == run_id

            # Idempotent re-run: no duplicate, no second notification.
            mock_notify.reset_mock()
            assert generate_weekly_checkin("2026-10-28") == run_id
            mock_notify.assert_not_called()

        run = hitl.get_run(run_id, conn)
        assert run["display_type"] == "weekly_checkin"
        assert run["handler"] == "coach.apply_weekly_checkin"
        questions = hitl.get_questions_by_set(run_id, "initial", conn)
        assert len(questions) == 4
        by_key = {q["question_key"]: q for q in questions}
        assert by_key[QUESTION_NOTE]["is_required"] == 1
        assert by_key[QUESTION_NOTE]["prompt"] == "生成された問い文"
        assert by_key[QUESTION_NEXT_STEP]["is_required"] == 0
        assert by_key[QUESTION_DECISION]["is_required"] == 1
        assert {c["value"] for c in by_key[QUESTION_DECISION]["choices"]} == {
            "continue",
            "narrow",
            "change",
            "pause",
        }
        assert by_key[QUESTION_TARGET_FOCUS]["is_required"] == 0
    finally:
        conn.close()


def test_generate_returns_none_without_eligible_target(
    test_memory_db_path, monkeypatch
):
    monkeypatch.setattr(
        "obsidian_ai_hub.coach.weekly_checkin.llm_client.generate_llm_response",
        lambda *a, **kw: "Q",
    )
    with patch("obsidian_ai_hub.line_notification.notify_hitl_run") as mock_notify:
        assert generate_weekly_checkin("2026-10-28") is None
        mock_notify.assert_not_called()


def test_generate_uses_fallback_when_llm_fails(test_memory_db_path, monkeypatch):
    _make_goal_with_focus()
    conn = get_db_connection()
    try:

        def _boom(*a, **kw):
            raise RuntimeError("LLM down")

        monkeypatch.setattr(
            "obsidian_ai_hub.coach.weekly_checkin.llm_client.generate_llm_response",
            _boom,
        )
        with patch("obsidian_ai_hub.line_notification.notify_hitl_run"):
            run_id = generate_weekly_checkin("2026-10-28")
        questions = hitl.get_questions_by_set(run_id, "initial", conn)
        note_q = next(q for q in questions if q["question_key"] == QUESTION_NOTE)
        assert "週1アウトプット" in note_q["prompt"]
    finally:
        conn.close()


def test_build_question_passes_previous_step_as_reference(
    test_memory_db_path, monkeypatch
):
    svc, goal = _make_goal_with_focus()
    focus = goal["active_focus"]
    svc.create_weekly_reflection(
        focus_id=focus["focus_id"],
        iso_week_monday="2026-10-19",
        worked_well=None,
        difficult_reason=None,
        learnings="朝の挨拶を続けられた",
        next_week_scope="朝一番にひと声かける",
        decision_type="continue",
    )
    conn = get_db_connection()
    try:
        store = CoachStore()
        latest = store.get_latest_reflection_for_goal(conn, goal["goal_id"])
        assert latest is not None
        assert latest["next_week_scope"] == "朝一番にひと声かける"

        captured = {}

        def _fake_render(path, context):
            captured.update(context)
            return "rendered"

        monkeypatch.setattr(
            "obsidian_ai_hub.coach.weekly_checkin.prompt.render_prompt", _fake_render
        )
        monkeypatch.setattr(
            "obsidian_ai_hub.coach.weekly_checkin.llm_client.generate_llm_response",
            lambda *a, **kw: "今週はどうでしたか？",
        )
        question, reference = build_checkin_question(goal, focus, latest, "", "")
        assert question == "今週はどうでしたか？"
        # The previous next_week_scope must reach the generator input.
        assert reference["latest_next_week_scope"] == "朝一番にひと声かける"
        assert "朝一番にひと声かける" in captured["LATEST_REFLECTION"]
    finally:
        conn.close()


def test_fallback_question_references_previous_step():
    latest = {"next_week_scope": "朝一番にひと声かける", "learnings": ""}
    text = _fallback_question("週1アウトプット", latest)
    assert "朝一番にひと声かける" in text
    assert "できましたか" not in text
    plain = _fallback_question("週1アウトプット", None)
    assert plain == "今週は Focus『週1アウトプット』に向けてどんな1週間でしたか？"


def test_select_target_rotates_to_oldest_reflection(test_memory_db_path):
    svc1, goal1 = _make_goal_with_focus(reason="理由1")
    svc = CoachService()
    goal2 = svc.create_goal("体力をつける", "理由2", ["毎朝散歩"])
    conn = get_db_connection()
    try:
        store = CoachStore()
        # Only goal1 has a reflection, so goal2 (never answered) comes first.
        svc1.create_weekly_reflection(
            focus_id=goal1["active_focus"]["focus_id"],
            iso_week_monday="2026-10-19",
            worked_well=None,
            difficult_reason=None,
            learnings="やった",
            next_week_scope=None,
            decision_type="continue",
        )
        selected = select_checkin_target(conn, store)
        assert selected is not None
        picked_goal, _, latest = selected
        assert picked_goal["goal_id"] == goal2["goal_id"]
        assert latest is None
    finally:
        conn.close()


def test_answer_flow_creates_reflection_and_thread_event(
    test_memory_db_path, monkeypatch
):
    _make_goal_with_focus()
    conn = get_db_connection()
    try:
        monkeypatch.setattr(
            "obsidian_ai_hub.coach.weekly_checkin.llm_client.generate_llm_response",
            lambda *a, **kw: "今週はどうでしたか？",
        )
        with patch("obsidian_ai_hub.line_notification.notify_hitl_run"):
            run_id = generate_weekly_checkin("2026-10-28")

        _answer_all(
            run_id,
            note="声をかけられた",
            decision="continue",
            next_step="来週も続ける",
            conn=conn,
        )
        assert dispatch_runs(conn) == 1

        run = hitl.get_run(run_id, conn)
        assert run["status"] == "completed"

        rows = conn.execute(
            "SELECT * FROM coach_weekly_reflections WHERE iso_week_monday = '2026-10-26'"
        ).fetchall()
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["learnings"] == "声をかけられた"
        assert row["next_week_scope"] == "来週も続ける"
        assert row["decision_type"] == "continue"

        events = conn.execute(
            "SELECT event_type FROM coach_thread_events WHERE reflection_id = ?",
            (row["reflection_id"],),
        ).fetchall()
        assert [dict(e)["event_type"] for e in events] == ["reflection_created"]
    finally:
        conn.close()


def test_pause_decision_pauses_focus(test_memory_db_path, monkeypatch):
    svc, goal = _make_goal_with_focus()
    focus_id = goal["active_focus"]["focus_id"]
    conn = get_db_connection()
    try:
        monkeypatch.setattr(
            "obsidian_ai_hub.coach.weekly_checkin.llm_client.generate_llm_response",
            lambda *a, **kw: "Q",
        )
        with patch("obsidian_ai_hub.line_notification.notify_hitl_run"):
            run_id = generate_weekly_checkin("2026-10-28")
        _answer_all(run_id, decision="pause", conn=conn)
        assert dispatch_runs(conn) == 1
        assert hitl.get_run(run_id, conn)["status"] == "completed"
        store = CoachStore()
        assert store.get_focus(conn, focus_id)["status"] == "paused"
    finally:
        conn.close()


def test_change_without_target_fails_without_reflection(
    test_memory_db_path, monkeypatch
):
    _make_goal_with_focus()
    conn = get_db_connection()
    try:
        monkeypatch.setattr(
            "obsidian_ai_hub.coach.weekly_checkin.llm_client.generate_llm_response",
            lambda *a, **kw: "Q",
        )
        with patch("obsidian_ai_hub.line_notification.notify_hitl_run"):
            run_id = generate_weekly_checkin("2026-10-28")
        _answer_all(run_id, decision="change", conn=conn)
        assert dispatch_runs(conn) == 1
        run = hitl.get_run(run_id, conn)
        assert run["status"] == "failed"
        assert "切替先" in (run["error_message"] or "")
        count = conn.execute(
            "SELECT COUNT(*) FROM coach_weekly_reflections"
        ).fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_change_with_target_switches_focus(test_memory_db_path, monkeypatch):
    svc, goal = _make_goal_with_focus()
    current_id = goal["active_focus"]["focus_id"]
    other = next(f for f in goal["focuses"] if f["focus_id"] != current_id)
    conn = get_db_connection()
    try:
        monkeypatch.setattr(
            "obsidian_ai_hub.coach.weekly_checkin.llm_client.generate_llm_response",
            lambda *a, **kw: "Q",
        )
        with patch("obsidian_ai_hub.line_notification.notify_hitl_run"):
            run_id = generate_weekly_checkin("2026-10-28")
        questions = hitl.get_questions_by_set(run_id, "initial", conn)
        target_q = next(
            q for q in questions if q["question_key"] == QUESTION_TARGET_FOCUS
        )
        assert other["focus_id"] in [c["value"] for c in target_q["choices"]]
        assert current_id not in [c["value"] for c in target_q["choices"]]

        _answer_all(run_id, decision="change", target=other["focus_id"], conn=conn)
        assert dispatch_runs(conn) == 1
        assert hitl.get_run(run_id, conn)["status"] == "completed"
        store = CoachStore()
        assert store.get_focus(conn, other["focus_id"])["status"] == "active"
        assert store.get_focus(conn, current_id)["status"] == "candidate"
    finally:
        conn.close()


def test_duplicate_week_completes_without_double_write(
    test_memory_db_path, monkeypatch
):
    svc, goal = _make_goal_with_focus()
    svc.create_weekly_reflection(
        focus_id=goal["active_focus"]["focus_id"],
        iso_week_monday="2026-10-26",
        worked_well=None,
        difficult_reason=None,
        learnings="既存",
        next_week_scope=None,
        decision_type="continue",
    )
    conn = get_db_connection()
    try:
        monkeypatch.setattr(
            "obsidian_ai_hub.coach.weekly_checkin.llm_client.generate_llm_response",
            lambda *a, **kw: "Q",
        )
        with patch("obsidian_ai_hub.line_notification.notify_hitl_run"):
            run_id = generate_weekly_checkin("2026-10-28")
        _answer_all(run_id, note="重複回答", conn=conn)
        assert dispatch_runs(conn) == 1
        assert hitl.get_run(run_id, conn)["status"] == "completed"
        count = conn.execute(
            "SELECT COUNT(*) FROM coach_weekly_reflections WHERE iso_week_monday = '2026-10-26'"
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_paused_goal_fails_without_write(test_memory_db_path, monkeypatch):
    svc, goal = _make_goal_with_focus()
    conn = get_db_connection()
    try:
        monkeypatch.setattr(
            "obsidian_ai_hub.coach.weekly_checkin.llm_client.generate_llm_response",
            lambda *a, **kw: "Q",
        )
        with patch("obsidian_ai_hub.line_notification.notify_hitl_run"):
            run_id = generate_weekly_checkin("2026-10-28")
        svc.pause_goal(goal["goal_id"])
        _answer_all(run_id, conn=conn)
        assert dispatch_runs(conn) == 1
        assert hitl.get_run(run_id, conn)["status"] == "failed"
        count = conn.execute(
            "SELECT COUNT(*) FROM coach_weekly_reflections"
        ).fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_expired_required_question_cancels_without_reflection(test_memory_db_path):
    svc, goal = _make_goal_with_focus()
    conn = get_db_connection()
    try:
        from obsidian_ai_hub.hitl.service import register_run_and_questions

        checkpoint = json.dumps(
            {
                "goal_id": goal["goal_id"],
                "focus_id": goal["active_focus"]["focus_id"],
                "iso_week_monday": "2026-10-26",
            }
        )
        register_run_and_questions(
            run_id="coach_checkin_2026-W44",
            handler="coach.apply_weekly_checkin",
            checkpoint=checkpoint,
            question_set_id="initial",
            questions_data=[
                {
                    "question_key": QUESTION_NOTE,
                    "question_type": "text",
                    "display_text": "Q",
                    "is_required": 1,
                    "expires_at": "2026-01-01T09:00:00+09:00",
                },
            ],
            conn=conn,
            title="週次チェックイン",
            display_type="weekly_checkin",
        )
        assert dispatch_runs(conn) == 0
        assert hitl.get_run("coach_checkin_2026-W44", conn)["status"] == "cancelled"
        count = conn.execute(
            "SELECT COUNT(*) FROM coach_weekly_reflections"
        ).fetchone()[0]
        assert count == 0
    finally:
        conn.close()
