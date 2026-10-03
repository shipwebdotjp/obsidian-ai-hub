import json
from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest

from obsidian_ai_hub.summerize_day import (
    load_activity_logs,
    get_daily_structured_record,
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
        project["project_id"], "opencode", "/private/repo", title="実装セッション"
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
            "backend": "opencode",
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
