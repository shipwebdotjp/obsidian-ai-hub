import json
from unittest.mock import patch
import pytest

from obsidian_ai_hub.agents import registry
from obsidian_ai_hub.hitl.store import get_run


def test_list_available_tools():
    tools = registry.list_available_tools()
    tool_ids = [t["tool_id"] for t in tools]
    expected_ids = [
        "web_search",
        "web_extract",
        "vault_search",
        "vault_read_file",
        "calendar_read",
        "reminders_read",
        "calendar_create_proposal",
        "reminder_create_proposal",
    ]
    assert tool_ids == expected_ids


def test_resolve_tools():
    # Deduplication and filtering unknown tools
    resolved = registry.resolve_tools(
        ["web_search", "web_search", "unknown_tool", "calendar_read"]
    )
    names = [t.name for t in resolved]
    assert len(resolved) == 2
    assert "web_search" in names
    assert "calendar_read" in names


def test_calendar_create_proposal():
    proposal_tool = registry.calendar_create_proposal
    res_str = proposal_tool.invoke(
        {
            "title": "チームミーティング",
            "start_time": "2026-08-25T14:00:00+09:00",
            "location": "会議室A",
            "content": "週次進捗確認のミーティング",
        }
    )
    res = json.loads(res_str)
    assert res["status"] == "proposed"
    assert "hitl_run_id" in res
    assert res["hitl_run_id"].startswith("hrun_inbox_calendar_")

    # Check that a HITL run was created in DB
    run = get_run(res["hitl_run_id"])
    assert run is not None
    assert run["handler"] == "calendar.add_approved_event"
    assert run["status"] == "pending_user"


def test_reminder_create_proposal():
    proposal_tool = registry.reminder_create_proposal
    res_str = proposal_tool.invoke(
        {
            "title": "資料を提出する",
            "due_date": "2026-08-25",
            "content": "月次レポートの提出",
        }
    )
    res = json.loads(res_str)
    assert res["status"] == "proposed"
    assert "hitl_run_id" in res
    assert res["hitl_run_id"].startswith("hrun_inbox_reminder_")

    # Check that a HITL run was created in DB
    run = get_run(res["hitl_run_id"])
    assert run is not None
    assert run["handler"] == "reminders.add_approved_reminder"
    assert run["status"] == "pending_user"


def test_vault_read_file_error():
    res_str = registry.vault_read_file.invoke({"relative_path": "non_existent.md"})
    res = json.loads(res_str)
    assert "error" in res


def test_calendar_read_mocked():
    with patch(
        "obsidian_ai_hub.agents.registry.fetch_calendar_events"
    ) as mock_fetch:
        mock_fetch.return_value = [
            {"title": "テストイベント", "start": "2026-08-25T10:00:00+09:00"}
        ]
        res_str = registry.calendar_read.invoke(
            {"start_date": "2026-08-25", "end_date": "2026-08-25"}
        )
        res = json.loads(res_str)
        assert len(res["events"]) == 1
        assert res["events"][0]["title"] == "テストイベント"
