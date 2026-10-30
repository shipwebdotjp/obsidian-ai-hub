"""Weekly check-in delivered as HITL questions.

Replaces the Sunday 17:30 weekly-review-draft LINE push with a HITL run that
asks one generated question about the week plus an optional next step and a
required next-week decision. Answers are written back through the existing
Coach reflection path (``CoachService.create_weekly_reflection``).
"""

from __future__ import annotations

import json
import logging
from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from obsidian_ai_hub.coach.exceptions import (
    CoachDuplicateReflectionError,
    CoachFocusNotFoundError,
    CoachGoalNotFoundError,
    CoachStateValidationError,
)
from obsidian_ai_hub.coach.service import CoachService
from obsidian_ai_hub.coach.store import CoachStore
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl.dispatcher import HitlContext, HitlResult
from obsidian_ai_hub.utils import config, llm_client, prompt

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")

CHECKIN_DISPLAY_TYPE = "weekly_checkin"
CHECKIN_HANDLER = "coach.apply_weekly_checkin"

QUESTION_NOTE = "checkin_note"
QUESTION_NEXT_STEP = "checkin_next_step"
QUESTION_DECISION = "checkin_decision"
QUESTION_TARGET_FOCUS = "checkin_target_focus"

DECISION_CHOICES = [
    {
        "value": "continue",
        "label": "続ける",
        "description": "このまま同じ Focus で来週も進める",
    },
    {
        "value": "narrow",
        "label": "小さくする",
        "description": "範囲を狭めて続けやすくする（来週試すことを書く）",
    },
    {
        "value": "change",
        "label": "別の Focus へ",
        "description": "切り替える Focus を選ぶ",
    },
    {
        "value": "pause",
        "label": "休む",
        "description": "今週はこの Focus を休止する",
    },
]
DECISION_VALUES = {c["value"] for c in DECISION_CHOICES}

CHECKIN_EXPIRY_DAYS = 7
CHECKIN_QUESTION_MAX_CHARS = 500


def _coerce_target_date(target_date: datetime | date_type | str | None) -> datetime:
    if target_date is None:
        return datetime.now(JST)
    if isinstance(target_date, datetime):
        return target_date
    if isinstance(target_date, date_type):
        return datetime.combine(target_date, datetime.min.time())
    if isinstance(target_date, str):
        return datetime.strptime(target_date, "%Y-%m-%d")
    raise TypeError(f"Unsupported target_date type: {type(target_date)!r}")


def get_checkin_week_monday(
    target_date: datetime | date_type | str | None = None,
) -> str:
    """Return the ISO week Monday (YYYY-MM-DD) for the target date in JST."""
    target = _coerce_target_date(target_date)
    if target.tzinfo is None:
        target = target.replace(tzinfo=JST)
    else:
        target = target.astimezone(JST)
    monday = target.date() - timedelta(days=target.weekday())
    return monday.isoformat()


def run_id_for_week(iso_week_monday: str) -> str:
    """Return the idempotent HITL run id for a check-in week."""
    monday = date_type.fromisoformat(iso_week_monday)
    iso_year, iso_week, _ = monday.isocalendar()
    return f"coach_checkin_{iso_year}-W{iso_week:02d}"


def select_checkin_target(
    conn, store: Optional[CoachStore] = None
) -> Optional[tuple[dict[str, Any], dict[str, Any], Optional[dict[str, Any]]]]:
    """Select the (goal, focus, latest reflection) triple for this week's check-in.

    Only active goals with an active focus are eligible. When several goals
    are eligible, the one whose latest reflection is oldest (or never recorded)
    is picked so check-ins rotate instead of following an implicit priority.
    """
    store = store or CoachStore()
    candidates: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for goal in store.list_goals(conn, status="active"):
        focus = store.get_active_focus_for_goal(conn, goal["goal_id"])
        if not focus:
            continue
        latest_week = store.get_latest_reflection_week_for_goal(conn, goal["goal_id"])
        candidates.append((latest_week or "", goal, focus))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    _, goal, focus = candidates[0]
    latest = store.get_latest_reflection_for_goal(conn, goal["goal_id"])
    return goal, focus, latest


def _format_latest_reflection(latest: Optional[dict[str, Any]]) -> str:
    if not latest:
        return "(なし)"
    scope = (latest.get("next_week_scope") or "").strip()
    learnings = (latest.get("learnings") or "").strip()
    week = latest.get("iso_week_monday") or ""
    parts = [f"週: {week}"]
    if scope:
        parts.append(f"来週試すこと: {scope}")
    if learnings:
        parts.append(f"学び: {learnings}")
    if not scope and not learnings:
        return "(なし)"
    return "\n".join(parts)


def _fallback_question(focus_name: str, latest: Optional[dict[str, Any]]) -> str:
    scope = ((latest or {}).get("next_week_scope") or "").strip()
    if scope:
        return (
            f"先週は『{scope}』を試す週でした。"
            f"今週は Focus『{focus_name}』に向けてどんな1週間でしたか？"
        )
    return f"今週は Focus『{focus_name}』に向けてどんな1週間でしたか？"


def _clean_question_text(response: object, fallback: str) -> str:
    if not isinstance(response, str) or not response.strip():
        return fallback
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            text = "\n".join(lines[1:-1]).strip()
    text = " ".join(text.split())
    if not text:
        return fallback
    if len(text) > CHECKIN_QUESTION_MAX_CHARS:
        text = text[: CHECKIN_QUESTION_MAX_CHARS - 1] + "…"
    return text


def build_checkin_question(
    goal: dict[str, Any],
    focus: dict[str, Any],
    latest: Optional[dict[str, Any]],
    daily_notes: str,
    saved_draft: str,
) -> tuple[str, dict[str, Any]]:
    """Build the weekly check-in question text.

    Returns the question text and the reference material handed to the
    generator (used by tests to verify the previous step is referenced).
    """
    statement = str(goal.get("statement") or "").strip()
    reason = str(goal.get("reason") or "").strip()
    focus_name = str(focus.get("name") or "").strip()
    latest_text = _format_latest_reflection(latest)
    fallback = _fallback_question(focus_name, latest)
    reference = {
        "goal_statement": statement,
        "focus_name": focus_name,
        "latest_next_week_scope": ((latest or {}).get("next_week_scope") or "").strip(),
        "latest_learnings": ((latest or {}).get("learnings") or "").strip(),
        "has_daily_notes": bool(daily_notes.strip()),
    }
    try:
        rendered = prompt.render_prompt(
            config.COACH_CHECKIN_PROMPT_PATH,
            {
                "GOAL_STATEMENT": statement,
                "GOAL_REASON": f"（理由: {reason}）" if reason else "",
                "FOCUS_NAME": focus_name,
                "DAILY_NOTES": daily_notes or "(記録なし)",
                "SAVED_DRAFT": saved_draft or "(なし)",
                "LATEST_REFLECTION": latest_text,
            },
        )
        response = llm_client.generate_llm_response(
            provider=config.COACH_CHECKIN_PROVIDER,
            model=config.COACH_CHECKIN_MODEL,
            prompt=rendered,
            max_tokens=1024,
        )
        return _clean_question_text(response, fallback), reference
    except Exception as exc:
        logger.warning("Failed to generate check-in question, using fallback: %s", exc)
        return fallback, reference


def _collect_week_materials(target: datetime) -> tuple[str, str]:
    """Collect daily notes text and the saved review draft for the target week."""
    from obsidian_ai_hub import review_draft as review_draft_module

    daily_notes = review_draft_module._collect_existing_daily_notes(
        review_draft_module.get_week_dates(target)
    )
    saved_draft = ""
    try:
        weekly_note = review_draft_module.reader.get_weekly_note_content(target)
        match = review_draft_module._EMPTY_RESULT_RE.search(weekly_note)
        if match is not None:
            found = review_draft_module._get_saved_draft(weekly_note, match.end())
            saved_draft = found or ""
    except Exception as exc:
        logger.warning("Could not read saved review draft for check-in: %s", exc)
    return daily_notes, saved_draft


def generate_weekly_checkin(
    target_date: datetime | date_type | str | None = None,
) -> Optional[str]:
    """Register this week's check-in HITL run and notify. Idempotent per week.

    Returns the run id when a run was created (or already existed), or None
    when there is no eligible goal/focus to check in on.
    """
    from obsidian_ai_hub.hitl.service import register_run_and_questions
    from obsidian_ai_hub.hitl.store import get_run

    iso_week_monday = get_checkin_week_monday(target_date)
    run_id = run_id_for_week(iso_week_monday)
    target = _coerce_target_date(target_date)

    conn = get_db_connection()
    try:
        if get_run(run_id, conn):
            logger.info("Check-in run %s already exists; skipping generation", run_id)
            return run_id

        selected = select_checkin_target(conn)
        if selected is None:
            logger.info("No active goal/focus for weekly check-in; skipping")
            return None
        goal, focus, latest = selected

        daily_notes, saved_draft = _collect_week_materials(target)
        question, _reference = build_checkin_question(
            goal, focus, latest, daily_notes, saved_draft
        )

        store = CoachStore()
        candidate_focuses = [
            f
            for f in store.list_focuses_by_goal(conn, goal["goal_id"])
            if f["focus_id"] != focus["focus_id"] and f.get("status") != "ended"
        ]
        target_choices = [
            {"value": f["focus_id"], "label": str(f.get("name") or f["focus_id"])}
            for f in candidate_focuses
        ]

        now_jst = datetime.now(JST)
        expires_at = (now_jst + timedelta(days=CHECKIN_EXPIRY_DAYS)).isoformat()
        focus_name = str(focus.get("name") or "").strip()

        questions_data = [
            {
                "question_key": QUESTION_NOTE,
                "question_type": "text",
                "display_text": question,
                "is_required": 1,
                "sequence": 0,
                "title": "今週の振り返り",
                "prompt": question,
                "expires_at": expires_at,
            },
            {
                "question_key": QUESTION_NEXT_STEP,
                "question_type": "text",
                "display_text": "来週試したいこと（任意）",
                "is_required": 0,
                "sequence": 1,
                "title": "来週試したいこと",
                "prompt": "来週試したいこと（任意。一言でかまいません）",
                "expires_at": expires_at,
            },
            {
                "question_key": QUESTION_DECISION,
                "question_type": "select",
                "display_text": "来週はどうしますか？",
                "choices": DECISION_CHOICES,
                "is_required": 1,
                "sequence": 2,
                "title": "来週の扱い",
                "prompt": "来週はどうしますか？",
                "expires_at": expires_at,
            },
            {
                "question_key": QUESTION_TARGET_FOCUS,
                "question_type": "select",
                "display_text": "切り替える Focus を選んでください",
                "choices": target_choices,
                "is_required": 0,
                "sequence": 3,
                "title": "切替先の Focus",
                "prompt": "「別の Focus へ」を選んだ場合の切替先",
                "expires_at": expires_at,
            },
        ]

        checkpoint = json.dumps(
            {
                "goal_id": goal["goal_id"],
                "focus_id": focus["focus_id"],
                "iso_week_monday": iso_week_monday,
            }
        )
        register_run_and_questions(
            run_id=run_id,
            handler=CHECKIN_HANDLER,
            checkpoint=checkpoint,
            question_set_id="initial",
            questions_data=questions_data,
            conn=conn,
            title="週次チェックイン",
            description=f"{iso_week_monday} の週 Focus『{focus_name}』の振り返り",
            display_type=CHECKIN_DISPLAY_TYPE,
        )
        logger.info("Registered weekly check-in run %s", run_id)

        try:
            from obsidian_ai_hub.line_notification import notify_hitl_run

            notify_hitl_run(
                kind="週次チェックイン",
                title="週次チェックイン",
                description=f"{iso_week_monday} の週 Focus『{focus_name}』の振り返り",
                run_id=run_id,
            )
        except Exception as exc:
            logger.warning(
                "LINE check-in notification failed after commit for run %s: %s",
                run_id,
                type(exc).__name__,
            )
        return run_id
    finally:
        conn.close()


def _answer_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value", value.get("comment"))
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    text = value.strip()
    return text or None


def apply_weekly_checkin(context: HitlContext) -> HitlResult:
    """HITL handler: write check-in answers as a Coach weekly reflection."""
    try:
        checkpoint_data = json.loads(context.checkpoint or "")
    except (ValueError, TypeError) as exc:
        return HitlResult.fail(f"Invalid checkpoint format: {exc}")
    if not isinstance(checkpoint_data, dict):
        return HitlResult.fail("Invalid checkpoint format")

    goal_id = checkpoint_data.get("goal_id")
    focus_id = checkpoint_data.get("focus_id")
    iso_week_monday = checkpoint_data.get("iso_week_monday")
    if not goal_id or not focus_id or not iso_week_monday:
        return HitlResult.fail(
            "Missing goal_id, focus_id, or iso_week_monday in checkpoint"
        )

    answers = context.answers_by_question_key or {}
    note = _answer_text(answers.get(QUESTION_NOTE))
    if not note:
        return HitlResult.fail("今週の振り返りが未回答です")
    decision = _answer_text(answers.get(QUESTION_DECISION))
    if decision not in DECISION_VALUES:
        return HitlResult.fail("来週の扱いが未選択です")
    next_step = _answer_text(answers.get(QUESTION_NEXT_STEP))
    target_focus_id: Optional[str] = None
    if decision == "change":
        target_focus_id = _answer_text(answers.get(QUESTION_TARGET_FOCUS))
        if not target_focus_id:
            return HitlResult.fail("切替先の Focus を選んでください")
    if decision == "narrow" and not next_step:
        return HitlResult.fail(
            "「小さくする」を選んだ場合は来週試すことを書いてください"
        )

    service = CoachService()
    try:
        service.create_weekly_reflection(
            focus_id=focus_id,
            iso_week_monday=iso_week_monday,
            worked_well=None,
            difficult_reason=None,
            learnings=note,
            next_week_scope=next_step,
            decision_type=decision,
            target_focus_id=target_focus_id,
        )
    except CoachDuplicateReflectionError:
        logger.info(
            "Reflection for focus %s week %s already exists; treating as complete",
            focus_id,
            iso_week_monday,
        )
        return HitlResult.complete()
    except (
        CoachStateValidationError,
        CoachFocusNotFoundError,
        CoachGoalNotFoundError,
    ) as exc:
        return HitlResult.fail(str(exc))
    return HitlResult.complete()


def main(target_date: datetime | date_type | str | None = None) -> bool:
    """Generate this week's check-in run. Returns True when a run exists."""
    try:
        return generate_weekly_checkin(target_date) is not None
    except Exception as exc:
        logger.error("Failed to generate weekly check-in: %s", exc)
        return False


if __name__ == "__main__":
    main()
