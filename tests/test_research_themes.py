from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub import research_themes


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
    updated = research_themes.set_status(rec["theme_id"], "approved", reviewed_by="user")
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


def test_list_recent_activity_days(tmp_path: Path):
    today = date.today()
    log_dir = tmp_path / today.strftime("%Y") / today.strftime("%m")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{today.strftime('%Y-%m-%d')}.jsonl"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"summary": "テストアクティビティ", "category": "開発", "keywords": ["test"]}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"summary": "テストアクティビティ", "category": "開発", "keywords": ["test"]}, ensure_ascii=False) + "\n")
        f.write("broken json line\n")
        f.write(json.dumps({"summary": "別のアクティビティ", "category": "学習", "keywords": ["python"]}, ensure_ascii=False) + "\n")

    with patch.object(research_themes.config, "ACTIVITY_PATH", tmp_path):
        entries = research_themes.list_recent_activity_days(days=1)

    assert len(entries) == 2
    summaries = {e["summary"] for e in entries}
    assert "テストアクティビティ" in summaries
    assert "別のアクティビティ" in summaries
