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

from obsidian_ai_hub.utils.topics import TOPIC_ENUM, normalize_topics


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


@patch("obsidian_ai_hub.summerize_day.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record_passes_candidates(mock_fm, mock_path, mock_llm, mock_render):
    from datetime import datetime
    import json
    from obsidian_ai_hub.summerize_day import get_daily_structured_record

    target_date = datetime(2023, 10, 27)
    daily_content = "Content"

    mock_fm.return_value = None
    mock_p = MagicMock()
    mock_p.exists.return_value = True
    mock_path.return_value = mock_p

    # LLM returns topics with some outside the candidates and some duplicates
    mock_llm.return_value = json.dumps({
        "summary": "Summary",
        "topics": ["LLM・AI活用", "未知のトピック", "LLM・AI活用"]
    })

    mock_render.return_value = "Rendered Prompt"

    record = get_daily_structured_record(target_date, daily_content, [], [])

    # Check render_prompt is called with TOPIC_CANDIDATES
    mock_render.assert_called_once()
    context = mock_render.call_args[0][1]
    assert "TOPIC_CANDIDATES" in context
    candidates = json.loads(context["TOPIC_CANDIDATES"])
    assert "LLM・AI活用" in candidates
    assert "その他" in candidates

    # Check parsed and normalized topics in record
    assert record["topics"] == ["LLM・AI活用", "その他"]
