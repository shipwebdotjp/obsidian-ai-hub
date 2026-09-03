import json
from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub.summerize_day import (
    load_activity_logs,
    upsert_summary_record,
    get_daily_structured_record,
    format_structured_record_as_markdown,
)
from obsidian_ai_hub.summary.day_context import load_daily_session_overviews


@pytest.fixture
def mock_config(tmp_path):
    with patch("obsidian_ai_hub.summerize_day.config") as mock_cfg:
        mock_cfg.ACTIVITY_PATH = tmp_path / "activity"
        mock_cfg.AI_LOG_PATH = tmp_path / "ai_logs"
        yield mock_cfg


def test_load_activity_logs(mock_config):
    target_date = datetime(2023, 10, 27)
    mock_records = [
        {
            "occurred_at": "2023-10-27T10:00:00",
            "app_name": "App1",
            "window_title": "Title1",
            "summary": "Summary1",
            "category": None,
            "keywords": None,
            "extra": "data",
        },
        {
            "occurred_at": "2023-10-27T11:00:00",
            "app_name": "App2",
            "window_title": "Title2",
            "summary": "Summary2",
            "category": "開発",
            "keywords": ["python"],
        },
    ]

    with patch("obsidian_ai_hub.summerize_day.get_activities_by_date") as mock_get:
        mock_get.return_value = mock_records
        logs = load_activity_logs(target_date)

    assert len(logs) == 2
    assert logs[0]["app_name"] == "App1"
    assert "extra" not in logs[0]
    assert logs[1]["window_title"] == "Title2"
    # Check new fields defaults
    assert logs[0]["category"] == "その他"
    assert logs[0]["keywords"] == []


def test_load_activity_logs_no_file(mock_config):
    target_date = datetime(2023, 10, 27)
    with patch("obsidian_ai_hub.summerize_day.get_activities_by_date") as mock_get:
        mock_get.return_value = []
        logs = load_activity_logs(target_date)
    assert logs == []


def test_upsert_summary_record(mock_config, test_memory_db_path):
    record = {
        "period_type": "day",
        "period_key": "2023-10-27",
        "period_start": "2023-10-27",
        "period_end": "2023-10-27",
        "generated_at": "2023-10-27T22:00:00",
        "summary": "Day 27",
        "keywords": [],
        "mood": None,
        "sleep_raw": None,
        "sleep_hours": None,
        "topics": [],
        "projects": [],
        "people": [],
        "items": [],
    }
    upsert_summary_record(record)

    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM summaries WHERE period_type = ? AND period_key = ?",
            ("day", "2023-10-27"),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["summary"] == "Day 27"
    finally:
        conn.close()


@patch("obsidian_ai_hub.summerize_day.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record(
    mock_fm, mock_path, mock_llm, mock_render, mock_config, tmp_path
):
    target_date = datetime(2023, 10, 27)
    daily_content = "---\nmood: Happy\nsleep: 8h\n---\nContent"

    def fm_side_effect(text, key, default=None):
        if key == "mood":
            return "Happy"
        if key == "sleep":
            return "8h"
        return default

    mock_fm.side_effect = fm_side_effect

    mock_p = MagicMock()
    mock_p.exists.return_value = True
    mock_path.return_value = mock_p

    mock_llm.return_value = json.dumps(
        {
            "summary": "AI Structured Summary",
            "keywords": [" Python ", "Python", "Obsidian"],
            "topics": ["AI"],
            "highlights": ["Important decision"],
            "activities": ["Coding"],
            "people": [{"name": "Alice", "note": "Researcher"}],
        }
    )

    logs = [{"summary": "Session 1"}]
    activity_logs = [{"summary": "Activity 1"}, {"summary": "Activity 2"}]

    mock_render.return_value = "Rendered Prompt"

    record = get_daily_structured_record(
        target_date, daily_content, logs, activity_logs
    )

    assert record["period_type"] == "day"
    assert record["period_key"] == "2023-10-27"
    assert record["summary"] == "AI Structured Summary"
    assert record["keywords"] == ["Python", "Obsidian"]
    assert record["mood"] == "Happy"
    assert record["sleep_raw"] == "8h"
    assert record["sleep_hours"] == 8.0
    assert record["people"][0]["name"] == "Alice"
    assert any(
        i["kind"] == "highlights" and i["body"] == "Important decision"
        for i in record["items"]
    )
    assert any(
        i["kind"] == "activities" and i["body"] == "Coding" for i in record["items"]
    )


@patch("obsidian_ai_hub.summerize_day.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record_malformed_json(
    mock_fm, mock_path, mock_llm, mock_render, mock_config, tmp_path
):
    target_date = datetime(2023, 10, 27)
    daily_content = "---\nmood: Happy\n---"

    mock_fm.return_value = "Happy"
    mock_p = MagicMock()
    mock_p.exists.return_value = True
    mock_path.return_value = mock_p

    # LLM returns malformed JSON
    mock_llm.return_value = "This is not a JSON"

    logs = []
    activity_logs = [{"summary": "Act"}]

    with pytest.raises(json.JSONDecodeError):
        get_daily_structured_record(
            target_date, daily_content, logs, activity_logs
        )


@patch("obsidian_ai_hub.summerize_day.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record_truncated_fence(
    mock_fm, mock_path, mock_llm, mock_render, mock_config, tmp_path
):
    target_date = datetime(2023, 10, 27)
    daily_content = "Content"

    mock_fm.return_value = None
    mock_p = MagicMock()
    mock_p.exists.return_value = True
    mock_path.return_value = mock_p

    # LLM returns started code fence but no closing fence
    mock_llm.return_value = "```json\n{\"summary\": \"test\"}"

    logs = []
    activity_logs = []

    with pytest.raises(ValueError, match="truncated.*closing code fence"):
        get_daily_structured_record(
            target_date, daily_content, logs, activity_logs
        )


def test_format_structured_record_as_markdown():
    record = {
        "summary": "Today was productive.",
        "items": [
            {"kind": "highlights", "body": "Shipped feature", "display_order": 0},
            {"kind": "activities", "body": "Coding", "display_order": 0},
            {"kind": "learnings", "body": "Learned asyncio", "display_order": 0},
        ],
        "people": [{"name": "Alice", "note": "Discussed AI"}],
    }
    activity_logs = [
        {"category": "開発", "keywords": ["Python", "Git"]},
        {"category": "開発", "keywords": ["Python"]},
        {"category": "事務", "keywords": ["Email"]},
    ]

    markdown = format_structured_record_as_markdown(record, activity_logs)

    assert "Today was productive." in markdown
    assert "### ハイライト" in markdown
    assert "- Shipped feature" in markdown
    assert "### 活動内容" in markdown
    assert "- Coding" in markdown
    assert "### 学び・整理" in markdown
    assert "- Learned asyncio" in markdown
    assert "### 人物メモ" in markdown
    assert "- **Alice**: Discussed AI" in markdown
    assert "### カテゴリ順位" in markdown
    assert "- 開発: 2" in markdown
    assert "- 事務: 1" in markdown


@patch("obsidian_ai_hub.summerize_day.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record_strips_milliseconds(
    mock_fm, mock_path, mock_llm, mock_render, mock_config
):
    target_date = datetime(2023, 10, 27)
    mock_llm.return_value = json.dumps({"summary": "Test Summary"})
    mock_render.return_value = "Rendered Prompt"
    mock_p = MagicMock()
    mock_p.exists.return_value = True
    mock_path.return_value = mock_p

    activity_logs = [
        {"timestamp": "2023-10-27T10:00:00.123456", "summary": "Activity 1"}
    ]
    get_daily_structured_record(target_date, "content", [], activity_logs)

    # Verify render_prompt was called with stripped timestamp
    mock_render.assert_called_once()
    context = mock_render.call_args[0][1]
    assert "2023-10-27T10:00:00" in context["ACTIVITY_LOGS"]
    assert "2023-10-27T10:00:00.123456" not in context["ACTIVITY_LOGS"]


@patch("obsidian_ai_hub.summerize_day.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record_passes_activity_rankings(
    mock_fm, mock_path, mock_llm, mock_render, mock_config
):
    target_date = datetime(2023, 10, 27)
    mock_fm.return_value = None
    mock_path.return_value.exists.return_value = True
    mock_llm.return_value = json.dumps({"summary": "Test Summary"})
    mock_render.return_value = "Rendered Prompt"

    activity_logs = [
        {"summary": "Activity 1", "category": "開発", "keywords": ["Python", "Git"]},
        {"summary": "Activity 2", "category": "開発", "keywords": ["Python"]},
        {"summary": "Activity 3", "category": "事務", "keywords": ["Email"]},
    ]

    get_daily_structured_record(target_date, "content", [], activity_logs)

    context = mock_render.call_args[0][1]
    assert json.loads(context["CATEGORY_RANKINGS"]) == [["開発", 2], ["事務", 1]]
    assert json.loads(context["KEYWORD_RANKINGS"]) == [
        ["Python", 2],
        ["Git", 1],
        ["Email", 1],
    ]


def test_load_daily_session_overviews_uses_jst_start_date_and_metadata(
    monkeypatch, test_memory_db_path
):
    from obsidian_ai_hub.agents import store as agent_store
    from obsidian_ai_hub.coding import store as coding_store
    from obsidian_ai_hub.web.schemas import ProjectCreateRequest
    from obsidian_ai_hub.web.services.projects import create_project

    target = datetime(2023, 10, 27)

    agent_now = {"value": "2023-10-26T15:30:00+00:00"}  # 10/27 00:30 JST
    monkeypatch.setattr(agent_store, "_now_iso", lambda: agent_now["value"])
    agent = agent_store.create_agent("日次テストエージェント", "テスト用")
    included_agent_session = agent_store.create_session(agent["agent_id"], "相談セッション")
    user_message, agent_run = agent_store.start_user_run(
        included_agent_session["session_id"], "本文はコンテキストに含めない"
    )
    agent_store.complete_run(agent_run["run_id"], "この応答も含めない")

    agent_now["value"] = "2023-10-26T14:30:00+00:00"  # 10/26 23:30 JST
    excluded_agent_session = agent_store.create_session(agent["agent_id"], "前日開始")
    agent_now["value"] = "2023-10-27T01:00:00+00:00"
    agent_store.start_user_run(excluded_agent_session["session_id"], "当日活動だが除外")

    project = create_project(ProjectCreateRequest(display_name="日次集計プロジェクト"))
    coding_now = {"value": "2023-10-27T09:00:00+09:00"}
    monkeypatch.setattr(coding_store, "_now_iso", lambda: coding_now["value"])
    included_coding_session = coding_store.create_session(
        project["project_id"], "codex", "/private/repo", title="実装セッション"
    )
    coding_message = coding_store.add_message(
        included_coding_session["session_id"], "user", "本文はコンテキストに含めない"
    )
    coding_run = coding_store.create_run(
        included_coding_session["session_id"], coding_message["message_id"]
    )
    coding_store.update_run(coding_run["run_id"], status="completed")

    coding_now["value"] = "2023-10-26T23:00:00+09:00"
    excluded_coding_session = coding_store.create_session(
        project["project_id"], "opencode", "/private/old", title="前日開始"
    )
    coding_now["value"] = "2023-10-27T10:00:00+09:00"
    excluded_message = coding_store.add_message(
        excluded_coding_session["session_id"], "user", "当日活動だが除外"
    )
    coding_store.create_run(excluded_coding_session["session_id"], excluded_message["message_id"])

    agent_overviews, coding_overviews = load_daily_session_overviews(target)

    assert agent_overviews == [
        {
            "agent_name": "日次テストエージェント",
            "session_title": "相談セッション",
            "started_at": "2023-10-26T15:30:00+00:00",
            "message_count": 2,
            "user_message_count": 1,
            "assistant_message_count": 1,
            "run_status_counts": {"succeeded": 1},
        }
    ]
    assert coding_overviews == [
        {
            "project_id": project["project_id"],
            "project_name": "日次集計プロジェクト",
            "session_title": "実装セッション",
            "backend": "codex",
            "started_at": "2023-10-27T09:00:00+09:00",
            "run_count": 1,
            "run_status_counts": {"completed": 1},
        }
    ]
    assert "本文はコンテキストに含めない" not in json.dumps(
        [agent_overviews, coding_overviews], ensure_ascii=False
    )


@patch("obsidian_ai_hub.summerize_day.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record_passes_session_overviews(
    mock_fm, mock_llm, mock_render, mock_config
):
    mock_fm.return_value = None
    mock_llm.return_value = json.dumps({"summary": "Test Summary"})
    mock_render.return_value = "Rendered Prompt"
    agent_overviews = [{"agent_name": "助手", "session_title": "相談", "message_count": 2}]
    coding_overviews = [{"project_name": "Hub", "session_title": "実装", "run_count": 1}]

    get_daily_structured_record(
        datetime(2023, 10, 27),
        "Content",
        [],
        [],
        agent_overviews,
        coding_overviews,
    )

    context = mock_render.call_args[0][1]
    assert json.loads(context["AI_AGENT_SESSION_OVERVIEWS"]) == agent_overviews
    assert json.loads(context["CODING_SESSION_OVERVIEWS"]) == coding_overviews


@patch("obsidian_ai_hub.summerize_day.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record_passes_candidates(
    mock_fm, mock_path, mock_llm, mock_render, mock_config
):
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
    mock_llm.return_value = json.dumps(
        {
            "summary": "Summary",
            "topics": ["LLM・AI活用", "未知のトピック", "LLM・AI活用"],
        }
    )

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


@patch("obsidian_ai_hub.summerize_day.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
@patch("obsidian_ai_hub.summerize_day.research_db.list_approved_themes_by_date")
def test_get_daily_structured_record_passes_approved_research_themes(
    mock_list_approved, mock_fm, mock_path, mock_llm, mock_render, mock_config
):
    target_date = datetime(2023, 10, 27)
    daily_content = "Content"

    mock_fm.return_value = None
    mock_p = MagicMock()
    mock_p.exists.return_value = True
    mock_path.return_value = mock_p

    mock_list_approved.return_value = [
        {"theme_id": "rth_001", "theme": "LLM活用術", "direction": "調査方向A"},
        {"theme_id": "rth_002", "theme": "リマインダー自動化", "direction": None},
    ]

    mock_llm.return_value = json.dumps({"summary": "Test Summary"})
    mock_render.return_value = "Rendered Prompt"

    get_daily_structured_record(target_date, daily_content, [], [])

    context = mock_render.call_args[0][1]
    approved = json.loads(context["APPROVED_RESEARCH_THEMES"])
    assert len(approved) == 2
    assert approved[0]["theme"] == "LLM活用術"
    assert approved[0]["direction"] == "調査方向A"
    assert approved[1]["theme"] == "リマインダー自動化"
    assert "direction" not in approved[1]


@patch("obsidian_ai_hub.summerize_day.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
@patch("obsidian_ai_hub.summerize_day.research_db.list_approved_themes_by_date")
def test_get_daily_structured_record_approved_themes_empty_on_failure(
    mock_list_approved, mock_fm, mock_path, mock_llm, mock_render, mock_config
):
    target_date = datetime(2023, 10, 27)
    daily_content = "Content"

    mock_fm.return_value = None
    mock_p = MagicMock()
    mock_p.exists.return_value = True
    mock_path.return_value = mock_p

    mock_list_approved.side_effect = Exception("DB error")
    mock_llm.return_value = json.dumps({"summary": "Test Summary"})
    mock_render.return_value = "Rendered Prompt"

    record = get_daily_structured_record(target_date, daily_content, [], [])

    context = mock_render.call_args[0][1]
    assert json.loads(context["APPROVED_RESEARCH_THEMES"]) == []
    assert record["summary"] == "Test Summary"


@patch("obsidian_ai_hub.summerize_day.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record_project_notes(
    mock_fm, mock_path, mock_llm, mock_render, mock_config, tmp_path
):
    from obsidian_ai_hub.summerize_day import get_daily_structured_record

    target_date = datetime(2023, 10, 27)
    daily_content = "---\nmood: Happy\n---"

    mock_fm.return_value = "Happy"
    mock_p = MagicMock()
    mock_p.exists.return_value = True
    mock_path.return_value = mock_p

    mock_llm.return_value = json.dumps({
        "summary": "Summary with notes",
        "project_notes": [
            {"project_id": 1, "note": "Refactored auth module"},
            {"project_id": 2, "note": "Wrote tests"},
            {"project_id": 999, "note": "Invalid project"},
        ],
    })

    mock_render.return_value = "Rendered Prompt"

    with patch(
        "obsidian_ai_hub.summary.project_utils.get_active_projects_for_prompt",
        return_value=[
            {"id": 1, "display_name": "Project Alpha", "domain": "work"},
            {"id": 2, "display_name": "Project Beta", "domain": "personal"},
        ],
    ):
        record = get_daily_structured_record(target_date, daily_content, [], [])

    # Valid project IDs only, invalid 999 rejected
    assert len(record["project_notes"]) == 2
    pn1 = [p for p in record["project_notes"] if p["project_id"] == 1][0]
    assert pn1["note"] == "Refactored auth module"
    pn2 = [p for p in record["project_notes"] if p["project_id"] == 2][0]
    assert pn2["note"] == "Wrote tests"

    # project_ids derived from project_notes
    assert record["project_ids"] == [1, 2]
