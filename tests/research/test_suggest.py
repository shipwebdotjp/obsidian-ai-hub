from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub.research import suggest as suggest_research_theme


def _write_activity_log(base_dir: Path, activity_date: date, summaries: list[str]) -> Path:
    log_dir = base_dir / activity_date.strftime("%Y") / activity_date.strftime("%m")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{activity_date.strftime('%Y-%m-%d')}.jsonl"
    for s in summaries:
        record = json.dumps({"summary": s, "category": "開発", "keywords": ["test"]}, ensure_ascii=False)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(record + "\n")
    return log_file


def test_build_suggestions_uses_activity_context_and_avoids_existing(
    tmp_path: Path,
    monkeypatch,
    test_memory_db_path: Path,
):
    today = date.today()
    activity_root = tmp_path / "activity"

    _write_activity_log(activity_root, today, [
        "Obsidian の見出し設計を考える",
        "タスク管理の切り口を検討",
    ])
    _write_activity_log(activity_root, today - timedelta(days=1), [
        "ノート構造の見直し",
    ])

    monkeypatch.setattr(suggest_research_theme.config, "ACTIVITY_PATH", activity_root)

    from obsidian_ai_hub.research import db as research_themes
    assert suggest_research_theme.config.MEMORY_SQLITE_PATH == test_memory_db_path
    research_themes.create_theme(theme="既存テーマA", direction="既存の方向", kind="deep", confidence=0.9)
    rejected = research_themes.create_theme(theme="却下済みテーマ", direction="却下方向", kind="explore", confidence=0.5)
    research_themes.set_status(rejected["theme_id"], "rejected")

    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "deep",
                    "theme": "意思決定ログの設計",
                    "direction": "判断の前提と保留条件を残す方法を整理する",
                    "why_now": "最近のノートで判断の迷いが繰り返し出ているため",
                    "confidence": 0.95,
                },
                {
                    "kind": "adjacent",
                    "theme": "ノート構造と検索導線の接点",
                    "direction": "見出しとタグの設計が再検索性にどう効くかを調べる",
                    "why_now": "見出し設計の話題が直近で増えているため",
                    "confidence": 0.84,
                },
                {
                    "kind": "explore",
                    "theme": "調査メモの再利用パターン",
                    "direction": "読書メモを研究テーマに変換する方法を整理する",
                    "why_now": "読書メモの扱い方を見直す必要があるため",
                    "confidence": 0.76,
                },
                {
                    "kind": "deep",
                    "theme": "既存テーマA",
                    "direction": "既存の候補と同じ内容",
                    "why_now": "重複チェック用",
                    "confidence": 0.99,
                },
            ]
        },
        ensure_ascii=False,
    )

    def fake_llm_response(*, provider: str, model: str, prompt: str, temperature: float, max_tokens: int) -> str:
        assert "Obsidian の見出し設計" in prompt
        assert "既存テーマA" in prompt
        assert "[candidate]" in prompt
        assert "[rejected]" in prompt
        return llm_response

    with patch.object(suggest_research_theme.llm_client, "generate_llm_response", side_effect=fake_llm_response):
        suggestions = suggest_research_theme.build_suggestions()

    assert [item.kind for item in suggestions] == ["deep", "adjacent", "explore"]
    existing_keys = {suggest_research_theme._candidate_key(t.theme) for t in suggest_research_theme._load_existing_db_themes()}
    for item in suggestions:
        assert suggest_research_theme._candidate_key(item.theme) not in existing_keys
    assert len(suggestions) == 3


def test_build_suggestions_returns_empty_when_llm_output_is_invalid(tmp_path: Path, monkeypatch):
    today = date.today()
    activity_root = tmp_path / "activity"
    _write_activity_log(activity_root, today, ["テストアクティビティ"])
    monkeypatch.setattr(suggest_research_theme.config, "ACTIVITY_PATH", activity_root)

    with patch.object(suggest_research_theme.llm_client, "generate_llm_response", side_effect=RuntimeError("boom")):
        suggestions = suggest_research_theme.build_suggestions()

    assert suggestions == []


def test_main_creates_themes_and_researches(tmp_path: Path, monkeypatch):
    today = date.today()
    activity_root = tmp_path / "activity"
    _write_activity_log(activity_root, today, ["テストアクティビティ"])
    monkeypatch.setattr(suggest_research_theme.config, "ACTIVITY_PATH", activity_root)

    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "deep",
                    "theme": "生成テーマA",
                    "direction": "方向A",
                    "why_now": "理由A",
                    "confidence": 0.9,
                },
            ]
        },
        ensure_ascii=False,
    )

    with (
        patch.object(suggest_research_theme.llm_client, "generate_llm_response", return_value=llm_response),
        patch("obsidian_ai_hub.research.runner.run_theme_research") as mock_research,
    ):
        results = suggest_research_theme.main()

    assert len(results) == 1
    assert results[0]["status"] == "candidate"
    mock_research.assert_called_once()
