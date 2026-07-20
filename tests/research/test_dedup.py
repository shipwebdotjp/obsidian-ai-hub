from __future__ import annotations

from unittest.mock import patch

from obsidian_ai_hub.research import dedup as research_dedup


def test_run_dedup_no_similar():
    result = research_dedup.run_dedup_review("新テーマ", similar=None)
    assert result["decision"] == "distinct"
    assert result["failed"] is False


def test_run_dedup_empty_similar():
    result = research_dedup.run_dedup_review("新テーマ", similar=[])
    assert result["decision"] == "distinct"


def test_run_dedup_llm_duplicate():
    from obsidian_ai_hub.research import db as research_themes

    t1 = research_themes.create_theme(theme="既存テーマA", confidence=0.9)
    similar = [(t1["theme_id"], 0.95)]

    llm_response = (
        '{"decision": "duplicate", "target_theme_id": "'
        + t1["theme_id"]
        + '", "related_ids": [], "confidence": 0.98, "reason": "Same topic"}'
    )

    with patch.object(
        research_dedup.llm_client, "generate_llm_response", return_value=llm_response
    ):
        result = research_dedup.run_dedup_review("新テーマ", similar=similar)

    assert result["decision"] == "duplicate"
    assert result["target_theme_id"] == t1["theme_id"]
    assert result["failed"] is False


def test_run_dedup_llm_related():
    from obsidian_ai_hub.research import db as research_themes

    t1 = research_themes.create_theme(theme="関連テーマ", confidence=0.8)
    similar = [(t1["theme_id"], 0.85)]

    llm_response = (
        '{"decision": "related", "target_theme_id": null, "related_ids": ["'
        + t1["theme_id"]
        + '"], "confidence": 0.7, "reason": "Related topic"}'
    )

    with patch.object(
        research_dedup.llm_client, "generate_llm_response", return_value=llm_response
    ):
        result = research_dedup.run_dedup_review("新テーマ", similar=similar)

    assert result["decision"] == "related"
    assert t1["theme_id"] in result.get("related_ids", [])


def test_run_dedup_llm_distinct():
    from obsidian_ai_hub.research import db as research_themes

    t1 = research_themes.create_theme(theme="異なるテーマ", confidence=0.7)
    similar = [(t1["theme_id"], 0.72)]

    llm_response = '{"decision": "distinct", "target_theme_id": null, "related_ids": [], "confidence": 0.9, "reason": "Different topic"}'

    with patch.object(
        research_dedup.llm_client, "generate_llm_response", return_value=llm_response
    ):
        result = research_dedup.run_dedup_review("新テーマ", similar=similar)

    assert result["decision"] == "distinct"


def test_run_dedup_llm_failure():
    from obsidian_ai_hub.research import db as research_themes

    t1 = research_themes.create_theme(theme="何かのテーマ", confidence=0.6)
    similar = [(t1["theme_id"], 0.8)]

    with patch.object(
        research_dedup.llm_client,
        "generate_llm_response",
        side_effect=RuntimeError("LLM down"),
    ):
        result = research_dedup.run_dedup_review("新テーマ", similar=similar)

    assert result["decision"] == "distinct"
    assert result["failed"] is True


def test_run_dedup_invalid_json_response():
    from obsidian_ai_hub.research import db as research_themes

    t1 = research_themes.create_theme(theme="テーマ", confidence=0.5)
    similar = [(t1["theme_id"], 0.75)]

    with patch.object(
        research_dedup.llm_client,
        "generate_llm_response",
        return_value="not json at all",
    ):
        result = research_dedup.run_dedup_review("新テーマ", similar=similar)

    assert result["decision"] == "distinct"
    assert result["failed"] is True
