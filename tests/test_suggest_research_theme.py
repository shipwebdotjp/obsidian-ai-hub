from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub import suggest_research_theme


def _write_daily_note(base_dir: Path, note_date: date, content: str) -> Path:
    note_path = base_dir / note_date.strftime("%Y") / note_date.strftime("%m") / f"{note_date.strftime('%Y-%m-%d')}.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(content, encoding="utf-8")
    return note_path


def test_build_suggestions_uses_llm_context_and_avoids_existing_candidates(tmp_path: Path):
    daily_root = tmp_path / "daily"
    candidate_path = tmp_path / "リサーチ候補テーマリスト.md"
    candidate_path.write_text("- [ ] 既存テーマ / 既存の方向\n", encoding="utf-8")

    _write_daily_note(
        daily_root,
        date(2026, 5, 10),
        """---
title: 最近のメモ
---
# Obsidian の見出し設計
Obsidian のノート構造を見直す。
検索しやすい見出しを作る。
""",
    )
    _write_daily_note(
        daily_root,
        date(2026, 5, 9),
        """# 日次レビュー
タスク化の切り口を考える。
見返しやすい情報の粒度を整理する。
""",
    )
    _write_daily_note(
        daily_root,
        date(2026, 4, 1),
        """# 古い話題
古いノートは対象外にしたい。
""",
    )

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
                    "theme": "既存テーマ",
                    "direction": "既存の候補と同じ内容を繰り返し調べる",
                    "why_now": "重複チェック用",
                    "confidence": 0.99,
                },
            ]
        },
        ensure_ascii=False,
    )

    with (
        patch.object(suggest_research_theme.config, "DAILY_PATH", daily_root),
        patch.object(suggest_research_theme.config, "RESEARCH_CANDIDATE_THEME_LIST_PATH", candidate_path),
    ):
        def fake_llm_response(*, provider: str, model: str, prompt: str, temperature: float, max_tokens: int) -> str:
            assert provider == "openai"
            assert "最近のメモ" in prompt
            assert "Obsidian のノート構造を見直す。" in prompt
            assert "既存テーマ" in prompt
            return llm_response

        with patch.object(suggest_research_theme.llm_client, "generate_llm_response", side_effect=fake_llm_response):
            suggestions = suggest_research_theme.build_suggestions(as_of=date(2026, 5, 10))

    assert [item.kind for item in suggestions] == ["deep", "adjacent", "explore"]
    assert [item.theme for item in suggestions] == [
        "意思決定ログの設計",
        "ノート構造と検索導線の接点",
        "調査メモの再利用パターン",
    ]
    assert all(item.theme != "既存テーマ" for item in suggestions)


def test_build_suggestions_returns_empty_when_llm_output_is_invalid(tmp_path: Path):
    daily_root = tmp_path / "daily"
    _write_daily_note(
        daily_root,
        date(2026, 5, 10),
        """# 日次レビュー
タスク化の切り口を考える。
""",
    )

    with patch.object(suggest_research_theme.config, "DAILY_PATH", daily_root):
        with patch.object(suggest_research_theme.llm_client, "generate_llm_response", side_effect=RuntimeError("boom")):
            suggestions = suggest_research_theme.build_suggestions(as_of=date(2026, 5, 10))

    assert suggestions == []


def test_append_suggestions_writes_checkbox_lines_with_directions(tmp_path: Path):
    candidate_path = tmp_path / "リサーチ候補テーマリスト.md"
    suggestions = [
        suggest_research_theme.SuggestedResearchTheme("deep", "テーマA", "調査方向A"),
        suggest_research_theme.SuggestedResearchTheme("adjacent", "テーマB", "調査方向B"),
        suggest_research_theme.SuggestedResearchTheme("explore", "テーマC", "調査方向C"),
    ]

    with patch.object(suggest_research_theme.config, "RESEARCH_CANDIDATE_THEME_LIST_PATH", candidate_path):
        result_path = suggest_research_theme.append_suggestions(suggestions, candidate_path)

    assert result_path == candidate_path
    assert candidate_path.read_text(encoding="utf-8") == (
        "- [ ] テーマA / 調査方向A\n"
        "- [ ] テーマB / 調査方向B\n"
        "- [ ] テーマC / 調査方向C\n"
    )


def test_extract_preview_lines_skips_daily_template_noise():
    content = """---
title: 2026-05-10
date: 2026-05-10T00:00:00+09:00
tags:
  - daily
---
[[2026-05]]
[[2026-W19]]

```dataviewjs
await dv.view("views/dailynavigation",{})
```

# 2026/05/10 日曜日
## ☀️ 今日の天気
晴天
## 🚩今日の目標
- [ ] 何かをする
## 💡 今日の気づき・振り返り
- 会話の前に確認したほうがよかった
"""

    terms = suggest_research_theme._extract_preview_lines(content)

    assert "title" not in terms
    assert "date" not in terms
    assert "daily" not in terms
    assert "dataviewjs" not in terms
    assert "dailynavigation" not in terms
    assert "今日の天気" not in terms
    assert "今日の目標" not in terms
    assert "今日の気づき・振り返り" not in terms
    assert terms == ["- 会話の前に確認したほうがよかった"]


def test_build_context_pack_prefers_relevant_sections_over_template_noise():
    content = """---
title: 最近のメモ
---
[[2026-05]]

```dataviewjs
await dv.view("views/dailynavigation",{})
```

# 2026/05/10 日曜日
## ☀️ 今日の天気
晴天
## 🚩今日の目標
- [ ] 何かをする
## 💡 今日の気づき・振り返り
- 会話の前に確認したほうがよかった
## 📝メモ
- 次は先に事情を聞く
"""

    note = suggest_research_theme.RecentNote(
        note_date=date(2026, 5, 10),
        path=Path("2026-05-10.md"),
        content=content,
    )

    context = suggest_research_theme._build_context_pack([note])

    assert "dataviewjs" not in context
    assert "今日の天気" not in context
    assert "今日の目標" not in context
    assert "dailynavigation" not in context
    assert "2026-05-10" in context
    assert "会話の前に確認したほうがよかった" in context
    assert "次は先に事情を聞く" in context
