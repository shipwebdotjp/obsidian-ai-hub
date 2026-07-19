import sys
from unittest.mock import MagicMock, patch
import pytest

# Mock modules that might be missing in the environment
mock_modules = [
    "dotenv",
    "md_hybrid_search",
    "AppKit",
    "objc",
    "EventKit",
    "sentence_transformers",
    "torch",
    "transformers",
    "langchain",
    "langchain_openai",
    "langchain_community",
    "langchain_google_genai",
    "langchain_anthropic",
    "langchain_core",
    "langchain_core.messages",
    "langchain_core.tools",
    "yaml",
]
for module_name in mock_modules:
    if module_name not in sys.modules:
        sys.modules[module_name] = MagicMock()

from obsidian_ai_hub.utils.topics import TOPIC_ENUM, normalize_keywords, normalize_topics


def test_normalize_topics_as_is():
    # Candidates should be preserved as-is
    topics = ["LLM・AI活用", "AI・機械学習", "ソフトウェア開発"]
    result = normalize_topics(topics)
    assert result == ["LLM・AI活用", "AI・機械学習", "ソフトウェア開発"]


def test_normalize_topics_with_whitespace_and_nfkc():
    # Whitespace stripping and NFKC normalization
    topics = ["  LLM・AI活用  ", "ＡＩ・機械学習"]  # Zenkaku AI
    result = normalize_topics(topics)
    assert result == ["LLM・AI活用", "AI・機械学習"]


def test_normalize_topics_replaced_with_other():
    # Out of candidate topics replaced with その他 and deduplicated
    topics = ["未知のトピック", "別のトピック"]
    result = normalize_topics(topics)
    assert result == ["その他"]


def test_normalize_topics_mixed():
    # Mixed valid and non-candidate topics (capped at 5, maintaining order and deduplicated)
    topics = [
        "LLM・AI活用",
        "未知のトピック",  # replaced with "その他"
        "AI・機械学習",
        "別の未知のトピック",  # replaced with "その他" (duplicate, so removed)
        "ソフトウェア開発",
        "データ・分析",
        "クラウド・インフラ",
        "金融・投資"  # this exceeds the default limit of 5
    ]
    result = normalize_topics(topics, limit=5)
    assert result == [
        "LLM・AI活用",
        "その他",
        "AI・機械学習",
        "ソフトウェア開発",
        "データ・分析"
    ]


def test_normalize_topics_empty_or_none():
    assert normalize_topics([]) == []
    assert normalize_topics(None) == []


def test_normalize_keywords_trims_deduplicates_and_limits():
    keywords = [" Python ", "Python", "", None, 42, "Git", "LLM", "Obsidian", "SQLite", "Extra"]

    assert normalize_keywords(keywords) == ["Python", "Git", "LLM", "Obsidian", "SQLite", "Extra"]


def test_normalize_keywords_rejects_non_lists():
    assert normalize_keywords("Python") == []
    assert normalize_keywords(None) == []
