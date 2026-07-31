from __future__ import annotations

import json
import logging
from typing import Optional

from obsidian_ai_hub.utils.embeddings import get_embedder

logger = logging.getLogger(__name__)


import sqlite3
from obsidian_ai_hub.database import get_db_connection

def create_theme_and_research(
    *,
    theme: str,
    direction: Optional[str] = None,
    kind: str = "explore",
    why_now: str = "",
    confidence: float = 1.0,
    conn: Optional[sqlite3.Connection] = None,
    is_suggestion: bool = False,
) -> dict:
    from obsidian_ai_hub.research import db, dedup

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        with conn:
            normalized = db.normalize_theme_key(theme)
            existing = db.find_exact_duplicate(normalized, conn=conn)
            if existing:
                logger.info("Exact duplicate found for '%s': %s", theme, existing["theme_id"])
                db.create_theme(
                    theme=theme,
                    direction=direction,
                    kind=kind,
                    why_now=why_now,
                    confidence=confidence,
                    status="duplicate",
                    duplicate_of_theme_id=existing["theme_id"],
                    duplicate_reason="normalized exact match",
                    conn=conn,
                )
                return {"status": "duplicate", "theme_id": existing["theme_id"]}

            embedder = get_embedder()
            similar = db.find_top_similar(theme, embedder, k=5, conn=conn) if embedder else []

            decision = dedup.run_dedup_review(theme, direction, why_now, similar)
            logger.info(
                "Dedup decision for '%s': %s (failed=%s)",
                theme,
                decision["decision"],
                decision.get("failed"),
            )

            if decision["decision"] == "duplicate":
                target = decision["target_theme_id"]
                rec = db.create_theme(
                    theme=theme,
                    direction=direction,
                    kind=kind,
                    why_now=why_now,
                    confidence=confidence,
                    status="duplicate",
                    duplicate_of_theme_id=target,
                    duplicate_reason=decision.get("reason"),
                    conn=conn,
                )
                return {"status": "duplicate", "theme_id": rec["theme_id"]}

            rec = db.create_theme(
                theme=theme,
                direction=direction,
                kind=kind,
                why_now=why_now,
                confidence=confidence,
                status="candidate",
                related_theme_ids=decision.get("related_ids", []),
                duplicate_reason=decision.get("reason"),
                origin="auto_suggestion" if is_suggestion else None,
                conn=conn,
            )

            if is_suggestion:
                from obsidian_ai_hub.hitl.service import register_run_and_questions

                run_id = f"hrun_suggest_{rec['theme_id']}"
                questions_data = [
                    {
                        "question_key": "action",
                        "question_type": "select",
                        "display_text": f"「{theme}」を調査しますか？",
                        "title": "調査の実行",
                        "prompt": f"「{theme}」を調査しますか？",
                        "choices": [
                            {"value": "approve", "label": "調査を実行する"},
                            {"value": "reject", "label": "今回は見送る"}
                        ],
                        "is_required": 1,
                    }
                ]
                checkpoint = json.dumps({"theme_id": rec["theme_id"], "phase": "awaiting_approval"})
                register_run_and_questions(
                    run_id=run_id,
                    handler="research.run_approved_suggestion",
                    checkpoint=checkpoint,
                    question_set_id="confirm_suggest",
                    questions_data=questions_data,
                    conn=conn,
                    display_type="リサーチ提案",
                    title=f"「{theme}」を調査するか確認",
                    description="承認すると、このテーマを詳しく調査し、結果をVaultに保存します。",
                )
                # Save hitl_run_id on theme in the same transaction
                db._set_theme_field(rec["theme_id"], "hitl_run_id", run_id, conn=conn)
                logger.info(
                    "Registered HITL Run %s for suggested theme '%s'",
                    run_id,
                    theme,
                )
                return {"status": "candidate", "theme_id": rec["theme_id"], "hitl_run_id": run_id}

    finally:
        if close_conn:
            conn.close()

    if not is_suggestion:
        try:
            _run_research(rec["theme_id"])
        except Exception as exc:
            logger.exception(
                "Immediate research failed for theme %s: %s", rec["theme_id"], exc
            )

        job = db.latest_job(rec["theme_id"])
        return {"status": "candidate", "theme_id": rec["theme_id"], "job": job}


def _run_research(theme_id: str) -> None:
    from obsidian_ai_hub.research.runner import run_theme_research

    run_theme_research(theme_id)
