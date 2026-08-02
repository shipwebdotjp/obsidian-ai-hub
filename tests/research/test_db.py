from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from obsidian_ai_hub.research import db as research_themes


def test_normalize_theme_key():
    assert research_themes.normalize_theme_key("AI 研究") == "ai研究"
    assert research_themes.normalize_theme_key("　スペース ") == "スペース"
    assert research_themes.normalize_theme_key("ABC") == "abc"


def test_create_and_get_theme():
    rec = research_themes.create_theme(
        theme="テストテーマ",
        direction="調査方向",
        kind="deep",
        why_now="理由",
        confidence=0.9,
    )
    assert rec["theme"] == "テストテーマ"
    assert rec["direction"] == "調査方向"
    assert rec["status"] == "candidate"
    assert rec["theme_id"].startswith("rth_")

    fetched = research_themes.get_theme(rec["theme_id"])
    assert fetched is not None
    assert fetched["theme"] == "テストテーマ"


def test_find_exact_duplicate():
    normalized = research_themes.normalize_theme_key("重複テスト")
    found = research_themes.find_exact_duplicate(normalized)
    if found:
        research_themes.set_status(found["theme_id"], "duplicate", reviewed_by="system")

    research_themes.create_theme(theme="重複テスト", confidence=0.5)
    dup = research_themes.find_exact_duplicate(normalized)
    assert dup is not None
    assert dup["normalized_key"] == normalized


def test_list_themes():
    research_themes.create_theme(theme="一覧テストA", kind="deep", confidence=0.8)
    research_themes.create_theme(theme="一覧テストB", kind="adjacent", confidence=0.6)
    all_themes = research_themes.list_themes()
    themes = [t for t in all_themes if "一覧テスト" in t["theme"]]
    assert len(themes) >= 2


def test_set_status():
    rec = research_themes.create_theme(theme="ステータステスト", confidence=0.5)
    updated = research_themes.set_status(
        rec["theme_id"], "approved", reviewed_by="user"
    )
    assert updated is not None
    assert updated["status"] == "approved"
    assert updated["reviewed_by"] == "user"


def test_create_and_update_job():
    rec = research_themes.create_theme(theme="ジョブテスト", confidence=0.5)
    job = research_themes.create_job(rec["theme_id"])
    assert job["status"] == "pending"
    assert job["theme_id"] == rec["theme_id"]

    updated = research_themes.update_job(job["job_id"], status="running")
    assert updated["status"] == "running"

    research_themes.update_job(
        job["job_id"],
        status="succeeded",
        generated_title="生成タイトル",
        mode="internal",
        markdown="# 結果",
    )
    latest = research_themes.latest_job(rec["theme_id"])
    assert latest is not None
    assert latest["status"] == "succeeded"
    assert latest["generated_title"] == "生成タイトル"


def test_list_recent_activity_days():
    mock_activities = [
        {
            "activity_date": date.today().isoformat(),
            "occurred_at": "2023-10-27T10:00:00",
            "summary": "テストアクティビティ",
            "category": "開発",
            "keywords": ["test"],
        },
        {
            "activity_date": date.today().isoformat(),
            "occurred_at": "2023-10-27T10:05:00",
            "summary": "テストアクティビティ",
            "category": "開発",
            "keywords": ["test"],
        },
        {
            "activity_date": date.today().isoformat(),
            "occurred_at": "2023-10-27T11:00:00",
            "summary": "別のアクティビティ",
            "category": "学習",
            "keywords": ["python"],
        },
    ]

    with patch("obsidian_ai_hub.activity.store.get_recent_activities") as mock_get:
        mock_get.return_value = mock_activities
        entries = research_themes.list_recent_activity_days(days=1)

    assert len(entries) == 2
    summaries = {e["summary"] for e in entries}
    assert "テストアクティビティ" in summaries
    assert "別のアクティビティ" in summaries


def test_theme_defaults_have_empty_feedback():
    rec = research_themes.create_theme(
        theme="フィードバック既定テーマ", confidence=0.5, origin="auto_suggestion"
    )
    fetched = research_themes.get_theme(rec["theme_id"])
    assert fetched["feedback_decision"] is None
    assert fetched["feedback_reason"] is None
    assert fetched["feedback_comment"] is None
    assert fetched["feedback_at"] is None


def test_set_theme_feedback_approve_saves_and_retrieves():
    rec = research_themes.create_theme(
        theme="フィードバック承認テーマ", confidence=0.5, origin="auto_suggestion"
    )
    updated = research_themes.set_theme_feedback(
        rec["theme_id"],
        status="approved",
        decision="approved",
        comment="方向性が良い",
        reviewed_by="user",
    )
    assert updated is not None
    assert updated["status"] == "approved"
    assert updated["feedback_decision"] == "approved"
    assert updated["feedback_reason"] is None
    assert updated["feedback_comment"] == "方向性が良い"
    assert updated["feedback_at"] is not None
    assert updated["reviewed_at"] is not None
    assert updated["reviewed_by"] == "user"

    fetched = research_themes.get_theme(rec["theme_id"])
    assert fetched["status"] == "approved"
    assert fetched["feedback_decision"] == "approved"
    assert fetched["feedback_comment"] == "方向性が良い"


def test_set_theme_feedback_reject_with_reason():
    rec = research_themes.create_theme(
        theme="フィードバック却下テーマ", confidence=0.5, origin="auto_suggestion"
    )
    updated = research_themes.set_theme_feedback(
        rec["theme_id"],
        status="rejected",
        decision="rejected",
        reason="not_now",
        comment="来月また検討",
    )
    assert updated["status"] == "rejected"
    assert updated["feedback_decision"] == "rejected"
    assert updated["feedback_reason"] == "not_now"
    assert updated["feedback_comment"] == "来月また検討"
    assert updated["feedback_at"] is not None


def test_set_theme_feedback_invalid_values():
    rec = research_themes.create_theme(theme="無効フィードバック", confidence=0.5)
    with pytest.raises(ValueError):
        research_themes.set_theme_feedback(
            rec["theme_id"], status="approved", decision="unknown"
        )
    with pytest.raises(ValueError):
        research_themes.set_theme_feedback(
            rec["theme_id"], status="approved", decision="approved", reason="bogus"
        )
    with pytest.raises(ValueError):
        research_themes.set_theme_feedback(
            rec["theme_id"], status="bogus", decision="approved"
        )
    with pytest.raises(ValueError):
        research_themes.set_theme_feedback(
            rec["theme_id"], status="approved", decision="rejected"
        )
    with pytest.raises(ValueError):
        research_themes.set_theme_feedback(
            rec["theme_id"], status="rejected", decision="approved", reason="vague"
        )


def test_set_theme_feedback_invalid_values_leave_theme_untouched():
    rec = research_themes.create_theme(
        theme="無効フィードバック後も未変更", confidence=0.5
    )
    for kwargs in (
        {"status": "approved", "decision": "rejected"},
        {"status": "approved", "decision": "approved", "reason": "vague"},
        {"status": "approved", "decision": "approved", "reason": "bogus"},
    ):
        with pytest.raises(ValueError):
            research_themes.set_theme_feedback(rec["theme_id"], **kwargs)
    fetched = research_themes.get_theme(rec["theme_id"])
    assert fetched["status"] == "candidate"
    assert fetched["feedback_decision"] is None
    assert fetched["feedback_reason"] is None
    assert fetched["feedback_at"] is None


def test_set_theme_feedback_missing_theme_returns_none():
    updated = research_themes.set_theme_feedback(
        "rth_nonexistent", status="approved", decision="approved"
    )
    assert updated is None


def test_list_theme_feedback_newest_first_and_limit():
    for i in range(3):
        rec = research_themes.create_theme(
            theme=f"フィードバック一覧{i}",
            confidence=0.5,
            origin="auto_suggestion",
        )
        research_themes.set_theme_feedback(
            rec["theme_id"],
            status="rejected",
            decision="rejected",
            reason="other",
            feedback_at=f"2026-01-0{i + 1}T10:00:00+09:00",
        )

    rows = research_themes.list_theme_feedback(limit=2)
    assert len(rows) == 2
    assert rows[0]["theme"] == "フィードバック一覧2"
    assert rows[1]["theme"] == "フィードバック一覧1"
    assert rows[0]["feedback_decision"] == "rejected"
    assert rows[0]["feedback_reason"] == "other"

    all_rows = research_themes.list_theme_feedback()
    assert [r["theme"] for r in all_rows] == [
        "フィードバック一覧2",
        "フィードバック一覧1",
        "フィードバック一覧0",
    ]
