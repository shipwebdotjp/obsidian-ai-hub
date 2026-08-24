import json
from unittest.mock import MagicMock, patch
import pytest
from langchain_core.messages import AIMessageChunk

from obsidian_ai_hub.agents import runtime, store
from obsidian_ai_hub.hitl.store import get_run


@pytest.mark.anyio
async def test_schedule_assistant_integration():
    # 1. Create Schedule Assistant Agent
    agent = store.create_agent(
        name="Schedule Assistant Integration Agent",
        system_prompt="You are a schedule assistant.",
        tool_ids=[
            "calendar_read",
            "reminders_read",
            "calendar_create_proposal",
            "reminder_create_proposal",
        ],
    )
    session = store.create_session(agent["agent_id"], title="予定相談")
    user_msg, run = store.start_user_run(
        session["session_id"], "明日10時にチーム会議を入れてください"
    )

    # Mock calendar read
    mock_events = [{"title": "既存予定", "start": "2026-08-25T09:00:00+09:00"}]

    mock_llm = MagicMock()

    async def astream(_messages):
        if mock_llm.astream.call_count == 1:
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "calendar_create_proposal",
                        "args": (
                            '{"title":"チーム会議","start_time":'
                            '"2026-08-25T10:00:00+09:00","content":'
                            '"明日10時にチーム会議を入れてください"}'
                        ),
                        "id": "call_prop_1",
                        "index": 0,
                    }
                ],
            )
        else:
            yield AIMessageChunk(
                content="チーム会議の予定追加申請（HITL）を作成しました。"
            )

    mock_llm.astream.side_effect = astream
    mock_llm.bind_tools.return_value = mock_llm

    with (
        patch(
            "obsidian_ai_hub.agents.runtime.create_langchain_llm", return_value=mock_llm
        ),
        patch(
            "obsidian_ai_hub.agents.registry.fetch_calendar_events",
            return_value=mock_events,
        ),
    ):
        events = []
        async for event_str in runtime.generate_agent_stream(
            agent=agent,
            session=session,
            run=run,
            history_messages=[user_msg],
            user_content="明日10時にチーム会議を入れてください",
        ):
            if event_str.startswith("data: "):
                data_json = json.loads(event_str[6:].strip())
                events.append(data_json)

    # Find done event
    done_event = next(e for e in events if e.get("type") == "done")

    assert done_event["type"] == "done"
    assert len(done_event["hitl_run_ids"]) == 1
    hitl_run_id = done_event["hitl_run_ids"][0]
    assert hitl_run_id.startswith("hrun_inbox_calendar_")

    # Verify HITL run exists in SQLite
    hitl_run = get_run(hitl_run_id)
    assert hitl_run is not None
    assert hitl_run["handler"] == "calendar.add_approved_event"
    assert hitl_run["status"] == "pending_user"
