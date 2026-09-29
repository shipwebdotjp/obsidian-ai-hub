from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from obsidian_ai_hub.coach import (
    CoachDuplicateReflectionError,
    CoachFocusNotFoundError,
    CoachGoalNotFoundError,
    CoachReflectionNotFoundError,
    CoachService,
    CoachStateValidationError,
)
from obsidian_ai_hub.coach.service import get_current_jst_iso_week_monday


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test_coach.db"
    monkeypatch.setenv("OBSIDIAN_AI_HUB_MEMORY_SQLITE_PATH", str(db_file))
    from obsidian_ai_hub.database import get_db_connection
    conn = get_db_connection()
    conn.close()


def test_coach_service_goal_lifecycle():
    svc = CoachService()

    goal = svc.create_goal(
        statement="技術力を磨く",
        reason="成長のため",
        initial_focuses=["週1アウトプット", "毎日15分読書"],
    )

    assert goal["statement"] == "技術力を磨く"
    assert goal["status"] == "active"
    assert len(goal["focuses"]) == 2
    assert goal["active_focus"]["name"] == "週1アウトプット"

    # Update goal
    updated = svc.update_goal(goal["goal_id"], statement="世界に通じる技術力を磨く")
    assert updated["statement"] == "世界に通じる技術力を磨く"

    # Pause goal
    paused = svc.pause_goal(goal["goal_id"])
    assert paused["status"] == "paused"

    # Resume goal
    resumed = svc.resume_goal(goal["goal_id"])
    assert resumed["status"] == "active"

    # End goal
    ended = svc.end_goal(goal["goal_id"])
    assert ended["status"] == "ended"

    # Cannot update ended goal
    with pytest.raises(CoachStateValidationError):
        svc.update_goal(goal["goal_id"], statement="変更テスト")


def test_coach_service_focus_operations():
    svc = CoachService()
    goal = svc.create_goal("語学力向上のため", "仕事のため", ["単語学習"])
    g_id = goal["goal_id"]

    f1 = goal["active_focus"]
    assert f1["status"] == "active"

    # Add candidate focus
    f2 = svc.create_focus(g_id, "シャドーイング")
    assert f2["status"] == "candidate"

    # Activate f2 -> demotes f1 to candidate
    f2_active = svc.activate_focus(f2["focus_id"])
    assert f2_active["status"] == "active"

    g_updated = svc.get_goal(g_id)
    assert g_updated["active_focus"]["focus_id"] == f2["focus_id"]
    f1_updated = [f for f in g_updated["focuses"] if f["focus_id"] == f1["focus_id"]][0]
    assert f1_updated["status"] == "candidate"

    # Pause f2
    f2_paused = svc.pause_focus(f2["focus_id"])
    assert f2_paused["status"] == "paused"


def test_coach_service_weekly_reflections():
    svc = CoachService()
    goal = svc.create_goal("健康的な体作り", "活力維持", ["週2回ジム", "23時就寝"])
    g_id = goal["goal_id"]
    f1 = goal["active_focus"]
    f2 = [f for f in goal["focuses"] if f["focus_id"] != f1["focus_id"]][0]

    current_monday = get_current_jst_iso_week_monday()
    prev_monday = (
        datetime.strptime(current_monday, "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")

    # 1. Continue decision on a past week (latest at recording time)
    refl1 = svc.create_weekly_reflection(
        focus_id=f1["focus_id"],
        iso_week_monday=prev_monday,
        worked_well="火・木に行けた",
        difficult_reason="水曜は残業",
        learnings="朝ジムが良い",
        next_week_scope="同じペースで続ける",
        decision_type="continue",
    )
    assert refl1["decision_type"] == "continue"

    # Duplicate reflection on same week raises error
    with pytest.raises(CoachDuplicateReflectionError):
        svc.create_weekly_reflection(
            focus_id=f1["focus_id"],
            iso_week_monday=prev_monday,
            worked_well="重複",
            difficult_reason=None,
            learnings=None,
            next_week_scope=None,
            decision_type="continue",
        )

    # 2. Narrow decision requires next_week_scope
    prev_monday_2 = (
        datetime.strptime(current_monday, "%Y-%m-%d") - timedelta(days=14)
    ).strftime("%Y-%m-%d")

    with pytest.raises(CoachStateValidationError):
        svc.create_weekly_reflection(
            focus_id=f1["focus_id"],
            iso_week_monday=prev_monday_2,
            worked_well=None,
            difficult_reason=None,
            learnings=None,
            next_week_scope="",  # blank rejected
            decision_type="narrow",
        )

    # 3. Change decision on the latest week switches active focus
    refl3 = svc.create_weekly_reflection(
        focus_id=f1["focus_id"],
        iso_week_monday=current_monday,
        worked_well="ジムは少しハードだった",
        difficult_reason="体調崩した",
        learnings="睡眠を優先すべき",
        next_week_scope="就寝時間を整える",
        decision_type="change",
        target_focus_id=f2["focus_id"],
    )
    assert refl3["decision_type"] == "change"

    # Verify focus switch
    g_after_change = svc.get_goal(g_id)
    assert g_after_change["active_focus"]["focus_id"] == f2["focus_id"]

    # 4. Reflection future week rejection
    future_monday = (
        datetime.strptime(current_monday, "%Y-%m-%d") + timedelta(days=7)
    ).strftime("%Y-%m-%d")

    with pytest.raises(CoachStateValidationError):
        svc.create_weekly_reflection(
            focus_id=f2["focus_id"],
            iso_week_monday=future_monday,
            worked_well=None,
            difficult_reason=None,
            learnings=None,
            next_week_scope=None,
            decision_type="continue",
        )


def test_coach_service_update_reflection_body_preserves_decision():
    svc = CoachService()
    goal = svc.create_goal("読書習慣", "知識習得", ["毎日20分"])
    f1 = goal["active_focus"]
    current_monday = get_current_jst_iso_week_monday()

    refl = svc.create_weekly_reflection(
        focus_id=f1["focus_id"],
        iso_week_monday=current_monday,
        worked_well="毎日読めた",
        difficult_reason=None,
        learnings="朝読書が集中できる",
        next_week_scope="継続",
        decision_type="continue",
    )

    # Update reflection body text
    updated_refl = svc.update_reflection(
        reflection_id=refl["reflection_id"],
        worked_well="毎日30分読めた（更新）",
        learnings="朝読書とメモ作成の組み合わせが良い",
    )

    assert updated_refl["worked_well"] == "毎日30分読めた（更新）"
    assert updated_refl["decision_type"] == "continue"  # preserved


def test_coach_service_reflection_on_non_active_focus():
    svc = CoachService()
    goal = svc.create_goal("語学力向上", "仕事のため", ["単語学習", "会話練習"])
    f1 = goal["active_focus"]
    f2 = [f for f in goal["focuses"] if f["focus_id"] != f1["focus_id"]][0]

    current_monday = get_current_jst_iso_week_monday()
    monday = datetime.strptime(current_monday, "%Y-%m-%d")
    prev_monday = (monday - timedelta(days=7)).strftime("%Y-%m-%d")
    prev_monday_2 = (monday - timedelta(days=14)).strftime("%Y-%m-%d")

    # Switch to f2 so f1 is no longer active.
    svc.activate_focus(f2["focus_id"])

    # Recording on a candidate (previously active) focus is allowed.
    refl = svc.create_weekly_reflection(
        focus_id=f1["focus_id"],
        iso_week_monday=prev_monday,
        worked_well="単語を100個",
        difficult_reason=None,
        learnings="朝が良い",
        next_week_scope="継続",
        decision_type="continue",
    )
    assert refl["focus_id"] == f1["focus_id"]

    # Recording on a paused focus is also allowed.
    svc.pause_focus(f1["focus_id"])
    refl2 = svc.create_weekly_reflection(
        focus_id=f1["focus_id"],
        iso_week_monday=prev_monday_2,
        worked_well=None,
        difficult_reason=None,
        learnings=None,
        next_week_scope=None,
        decision_type="continue",
    )
    assert refl2["focus_id"] == f1["focus_id"]

    # Present active focus is unchanged.
    assert svc.get_goal(goal["goal_id"])["active_focus"]["focus_id"] == f2["focus_id"]


def test_coach_service_backfill_change_does_not_switch_focus():
    svc = CoachService()
    goal = svc.create_goal("読書習慣づくり", "知識習得", ["朝読書", "夜読書", "週末読書"])
    g_id = goal["goal_id"]
    focuses = {f["name"]: f for f in goal["focuses"]}
    f1 = goal["active_focus"]
    f3 = focuses["週末読書"]

    current_monday = get_current_jst_iso_week_monday()
    prev_monday = (
        datetime.strptime(current_monday, "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")

    # Latest-week reflection first.
    svc.create_weekly_reflection(
        focus_id=f1["focus_id"],
        iso_week_monday=current_monday,
        worked_well="朝に読めた",
        difficult_reason=None,
        learnings=None,
        next_week_scope="継続",
        decision_type="continue",
    )

    # Backfill an older week with a change decision toward another candidate.
    refl = svc.create_weekly_reflection(
        focus_id=f1["focus_id"],
        iso_week_monday=prev_monday,
        worked_well="週末に切り替えたい",
        difficult_reason=None,
        learnings=None,
        next_week_scope=None,
        decision_type="change",
        target_focus_id=f3["focus_id"],
    )

    # Present state is unchanged.
    g = svc.get_goal(g_id)
    assert g["active_focus"]["focus_id"] == f1["focus_id"]
    f3_status = [f for f in g["focuses"] if f["focus_id"] == f3["focus_id"]][0]["status"]
    assert f3_status == "candidate"

    # Thread records the decision without applying the transition.
    events, _ = svc.list_thread_events(g_id, limit=200)
    refl_events = [
        e
        for e in events
        if e["event_type"] == "reflection_created"
        and e["reflection_id"] == refl["reflection_id"]
    ]
    assert len(refl_events) == 1
    assert refl_events[0]["payload"]["transition_applied"] is False
    assert not [
        e
        for e in events
        if e["event_type"] == "focus_activated" and e["focus_id"] == f3["focus_id"]
    ]


def test_coach_service_reflection_transition_events():
    svc = CoachService()
    goal = svc.create_goal("運動習慣", "健康維持", ["朝ラン", "夜ストレッチ"])
    g_id = goal["goal_id"]
    f1 = goal["active_focus"]
    f2 = [f for f in goal["focuses"] if f["focus_id"] != f1["focus_id"]][0]

    current_monday = get_current_jst_iso_week_monday()
    prev_monday = (
        datetime.strptime(current_monday, "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")

    # Latest-week change emits demote + activate events with snapshots.
    refl = svc.create_weekly_reflection(
        focus_id=f1["focus_id"],
        iso_week_monday=current_monday,
        worked_well="ランはハード",
        difficult_reason=None,
        learnings="ストレッチ優先",
        next_week_scope=None,
        decision_type="change",
        target_focus_id=f2["focus_id"],
    )

    events, _ = svc.list_thread_events(g_id, limit=200)
    demoted = [e for e in events if e["event_type"] == "focus_demoted"]
    assert len(demoted) == 1
    assert demoted[0]["focus_id"] == f1["focus_id"]
    assert demoted[0]["payload"]["focus_name"] == f1["name"]
    activated = [e for e in events if e["event_type"] == "focus_activated"]
    assert len(activated) == 1
    assert activated[0]["focus_id"] == f2["focus_id"]

    # Same-timestamp events keep deterministic insertion order
    # (reflection above its transitions in newest-first display).
    by_id = {e["event_id"]: i for i, e in enumerate(events)}
    refl_evt = [e for e in events if e["reflection_id"] == refl["reflection_id"]][0]
    assert by_id[refl_evt["event_id"]] < by_id[activated[0]["event_id"]] < by_id[demoted[0]["event_id"]]

    # Latest-week pause decision emits a pause event.
    svc.create_weekly_reflection(
        focus_id=f2["focus_id"],
        iso_week_monday=current_monday,
        worked_well=None,
        difficult_reason="多忙",
        learnings="量を減らす",
        next_week_scope=None,
        decision_type="pause",
    )
    events_after, _ = svc.list_thread_events(g_id, limit=200)
    paused = [e for e in events_after if e["event_type"] == "focus_paused"]
    assert len(paused) == 1
    assert paused[0]["focus_id"] == f2["focus_id"]
    assert svc.get_goal(g_id)["active_focus"] is None

    # Backfilled continue on the paused focus is history-only.
    svc.create_weekly_reflection(
        focus_id=f2["focus_id"],
        iso_week_monday=prev_monday,
        worked_well=None,
        difficult_reason="多忙だった",
        learnings=None,
        next_week_scope=None,
        decision_type="continue",
    )
    events_final, _ = svc.list_thread_events(g_id, limit=200)
    assert len([e for e in events_final if e["event_type"] == "focus_paused"]) == 1


def test_coach_service_reflection_body_update_reflected_in_thread():
    svc = CoachService()
    goal = svc.create_goal("執筆習慣", "発信のため", ["毎日500字"])
    g_id = goal["goal_id"]
    f1 = goal["active_focus"]
    current_monday = get_current_jst_iso_week_monday()

    refl = svc.create_weekly_reflection(
        focus_id=f1["focus_id"],
        iso_week_monday=current_monday,
        worked_well="毎日読めた",
        difficult_reason=None,
        learnings="朝読書が集中できる",
        next_week_scope="継続",
        decision_type="continue",
    )

    svc.update_reflection(
        reflection_id=refl["reflection_id"],
        worked_well="毎日30分読めた（更新）",
    )

    events, _ = svc.list_thread_events(g_id, limit=200)
    refl_events = [
        e
        for e in events
        if e["event_type"] == "reflection_created"
        and e["reflection_id"] == refl["reflection_id"]
    ]
    assert len(refl_events) == 1
    assert refl_events[0]["payload"]["worked_well"] == "毎日30分読めた（更新）"
    assert refl_events[0]["payload"]["decision_type"] == "continue"


def test_coach_service_manual_activate_emits_demoted_event():
    svc = CoachService()
    goal = svc.create_goal("料理", "健康のため", ["自炊", "作り置き"])
    g_id = goal["goal_id"]
    f1 = goal["active_focus"]
    f2 = [f for f in goal["focuses"] if f["focus_id"] != f1["focus_id"]][0]

    svc.activate_focus(f2["focus_id"])

    events, _ = svc.list_thread_events(g_id, limit=200)
    demoted = [e for e in events if e["event_type"] == "focus_demoted"]
    assert len(demoted) == 1
    assert demoted[0]["focus_id"] == f1["focus_id"]
    assert demoted[0]["payload"]["focus_name"] == f1["name"]


def test_coach_service_rename_focus_emits_event():
    svc = CoachService()
    goal = svc.create_goal("片付け", "快適な部屋", ["毎日5分"])
    g_id = goal["goal_id"]
    f1 = goal["active_focus"]

    svc.update_focus(f1["focus_id"], "毎朝5分片付け")

    events, _ = svc.list_thread_events(g_id, limit=200)
    renamed = [e for e in events if e["event_type"] == "focus_renamed"]
    assert len(renamed) == 1
    assert renamed[0]["payload"]["old_name"] == "毎日5分"
    assert renamed[0]["payload"]["new_name"] == "毎朝5分片付け"

    # Unchanged name emits no new event.
    svc.update_focus(f1["focus_id"], "毎朝5分片付け")
    events_after, _ = svc.list_thread_events(g_id, limit=200)
    assert len([e for e in events_after if e["event_type"] == "focus_renamed"]) == 1


def test_coach_service_change_target_must_differ_from_subject():
    svc = CoachService()
    goal = svc.create_goal("早起き", "朝時間確保", ["6時起床", "目覚まし2個"])
    f1 = goal["active_focus"]
    current_monday = get_current_jst_iso_week_monday()

    with pytest.raises(CoachStateValidationError):
        svc.create_weekly_reflection(
            focus_id=f1["focus_id"],
            iso_week_monday=current_monday,
            worked_well=None,
            difficult_reason=None,
            learnings=None,
            next_week_scope=None,
            decision_type="change",
            target_focus_id=f1["focus_id"],
        )


def test_coach_service_thread_events_snapshots():
    svc = CoachService()
    goal = svc.create_goal("目標A", "理由A", ["FocusA"])
    g_id = goal["goal_id"]

    # Update goal statement later
    svc.update_goal(g_id, statement="目標A_変更後")

    events, total = svc.list_thread_events(g_id)
    assert total >= 2
    created_event = [e for e in events if e["event_type"] == "goal_created"][0]
    # Snapshot retains original statement at event time
    assert created_event["payload"]["goal_statement"] == "目標A"
