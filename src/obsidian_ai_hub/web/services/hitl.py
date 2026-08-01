import sqlite3
from typing import Any, Optional

from obsidian_ai_hub.database import get_db_connection


# --- HITL services ---

def resolve_display_title(run: dict, conn: Optional[sqlite3.Connection] = None) -> str:
    # 1. Non-blank run.title
    title = run.get("title")
    if title and title.strip():
        return title.strip()

    # 2 & 3. Active question set
    active_set_id = run.get("active_question_set_id")
    if active_set_id:
        from obsidian_ai_hub.hitl import store as hitl_store
        questions = hitl_store.get_questions_by_set(run["run_id"], active_set_id, conn=conn)
        if questions:
            # First pending question
            target_q = None
            for q in questions:
                if q.get("status") == "pending":
                    target_q = q
                    break
            # If no pending question, first question
            if target_q is None:
                target_q = questions[0]

            # Check prompt -> display_text -> title
            for field in ["prompt", "display_text", "title"]:
                val = target_q.get(field)
                if val and val.strip():
                    return val.strip()

    # 4. Fallback
    return "確認待ちタスク"


def list_hitl_runs(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    from obsidian_ai_hub.hitl import store as hitl_store
    conn = get_db_connection()
    try:
        runs, total = hitl_store.list_runs(status=status, limit=limit, offset=offset, conn=conn)
        for r in runs:
            r["display_title"] = resolve_display_title(r, conn=conn)
        return runs, total
    finally:
        conn.close()


def get_hitl_run_detail(run_id: str) -> Optional[dict]:
    from obsidian_ai_hub.hitl import store as hitl_store
    conn = get_db_connection()
    try:
        run = hitl_store.get_run(run_id, conn=conn)
        if run is None:
            return None
        questions = hitl_store.get_all_questions_for_run(run_id, conn=conn)
        for q in questions:
            if "context_json" in q:
                q["context"] = q.pop("context_json")
        run_detail = dict(run)
        run_detail["questions"] = questions
        run_detail["display_title"] = resolve_display_title(run_detail, conn=conn)
        return run_detail
    finally:
        conn.close()


def submit_hitl_answer(run_id: str, question_key: str, answer: Any) -> None:
    from obsidian_ai_hub.hitl import service as hitl_service
    from obsidian_ai_hub.hitl import store as hitl_store
    run = hitl_store.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Run {run_id} not found")

    active_set_id = run.get("active_question_set_id")
    if not active_set_id:
        raise ValueError(f"No active question set for run {run_id}")

    hitl_service.submit_answer(run_id, active_set_id, question_key, answer)


def cancel_hitl_run(run_id: str) -> None:
    from obsidian_ai_hub.hitl import service as hitl_service
    hitl_service.cancel_run(run_id)
