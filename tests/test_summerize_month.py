import json
from datetime import datetime
from unittest.mock import patch
import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub import summerize_month
from obsidian_ai_hub.summary import store


@pytest.fixture
def mock_config(tmp_path):
    activity_path = tmp_path / "activity"
    daily_path = tmp_path / "daily"
    template_path = tmp_path / "template" / "daily.md"
    monthly_template_path = tmp_path / "template" / "monthly.md"

    activity_path.mkdir(parents=True, exist_ok=True)
    daily_path.mkdir(parents=True, exist_ok=True)
    monthly_template_path.parent.mkdir(parents=True, exist_ok=True)
    monthly_template_path.write_text("Default Monthly Template")

    with (
        patch("obsidian_ai_hub.utils.config.ACTIVITY_PATH", activity_path),
        patch("obsidian_ai_hub.utils.config.DAILY_PATH", daily_path),
        patch("obsidian_ai_hub.utils.config.TEMPLATE_PATH", template_path),
        patch(
            "obsidian_ai_hub.utils.config.MONTHLY_TEMPLATE_PATH", monthly_template_path
        ),
    ):
        yield


def test_load_weekly_records(mock_config, test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        for rec in [
            {
                "period_key": "2024-W40",
                "period_start": "2024-09-30",
                "period_end": "2024-10-06",
            },
            {
                "period_key": "2024-W41",
                "period_start": "2024-10-07",
                "period_end": "2024-10-13",
            },
            {
                "period_key": "2024-W44",
                "period_start": "2024-10-28",
                "period_end": "2024-11-03",
            },
            {
                "period_key": "2024-W45",
                "period_start": "2024-11-04",
                "period_end": "2024-11-10",
            },
        ]:
            store.upsert_summary(
                {
                    "period_type": "week",
                    "period_key": rec["period_key"],
                    "period_start": rec["period_start"],
                    "period_end": rec["period_end"],
                    "generated_at": "2024-10-01T22:00:00",
                    "summary": f"Week {rec['period_key']}",
                    "keywords": [],
                    "mood": None,
                    "sleep_raw": None,
                    "sleep_hours": None,
                    "topics": [],
                    "projects": [],
                    "people": [],
                    "items": [],
                },
                conn=conn,
            )
        conn.commit()
    finally:
        conn.close()

    # Test for October
    oct_dt = datetime(2024, 10, 1)
    loaded = summerize_month.load_weekly_records(oct_dt)
    assert len(loaded) == 3
    assert loaded[0]["period_key"] == "2024-W44"
    assert loaded[1]["period_key"] == "2024-W41"
    assert loaded[2]["period_key"] == "2024-W40"


@patch("obsidian_ai_hub.summerize_month.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_month.llm_client.generate_llm_response_detailed")
def test_summarize_month(mock_llm, mock_render, mock_config, test_memory_db_path):
    from obsidian_ai_hub.utils.llm_client import LLMResult

    mock_render.return_value = "Rendered Prompt"
    mock_llm.return_value = LLMResult(
        text=json.dumps(
            {
                "summary": "Monthly summary test",
                "keywords": [" Python ", "Python", "Obsidian"],
                "topics": ["LLM・AI活用"],
                "highlights": ["Highlight 1"],
                "progress": ["Progress 1"],
                "changes": ["Change 1"],
                "learnings": ["Learning 1"],
                "reflections": ["Reflection 1"],
                "patterns": ["Pattern 1"],
                "gratitude": ["Gratitude 1"],
                "people": [{"name": "Person 1", "note": "Note 1"}],
            }
        ),
        call_id="test-call-id",
        finish_reason="stop",
    )

    target_date = datetime(2024, 10, 1)

    conn = memory.get_db_connection()
    try:
        for rec in [
            {
                "period_key": "2024-W40",
                "period_start": "2024-09-30",
                "period_end": "2024-10-06",
            },
            {
                "period_key": "2024-W41",
                "period_start": "2024-10-07",
                "period_end": "2024-10-13",
            },
        ]:
            store.upsert_summary(
                {
                    "period_type": "week",
                    "period_key": rec["period_key"],
                    "period_start": rec["period_start"],
                    "period_end": rec["period_end"],
                    "generated_at": "2024-10-01T22:00:00",
                    "summary": f"Week {rec['period_key']}",
                    "keywords": [],
                    "mood": None,
                    "sleep_raw": None,
                    "sleep_hours": None,
                    "topics": [],
                    "projects": [],
                    "people": [],
                    "items": [],
                },
                conn=conn,
            )
        conn.commit()
    finally:
        conn.close()

    summerize_month.summarize_month(target_date)

    assert mock_llm.call_args[1]["max_tokens"] == 65536

    # Check SQLite output
    conn = memory.get_db_connection()
    try:
        row = store.get_summary_by_period("month", "2024-10", conn=conn)
        assert row is not None
        assert row["summary"] == "Monthly summary test"
        assert row["keywords"] == ["Python", "Obsidian"]
        assert row["mood"] is None
        assert row["sleep_hours"] is None
        assert len(row["items"]) == 7
        item_kinds = {i["kind"] for i in row["items"]}
        assert item_kinds == set(store.MONTH_ITEM_KINDS)
    finally:
        conn.close()


@patch("obsidian_ai_hub.summerize_month.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_month.llm_client.generate_llm_response_detailed")
def test_get_monthly_structured_record_does_not_inject_memories(
    mock_llm, mock_render, mock_config
):
    from obsidian_ai_hub.summerize_month import get_monthly_structured_record
    from obsidian_ai_hub.utils.llm_client import LLMResult

    mock_render.return_value = "Rendered Prompt"
    mock_llm.return_value = LLMResult(
        text=json.dumps({"summary": "Monthly summary"}),
        call_id="test-call-id",
        finish_reason="stop",
    )

    with patch(
        "obsidian_ai_hub.memory.context.compile_context_text",
        side_effect=AssertionError("must not compile memories"),
    ):
        record = get_monthly_structured_record(datetime(2024, 10, 1), [])

    assert record is not None
    assert record["summary"] == "Monthly summary"
    prompt_args = mock_render.call_args[0][1]
    assert "LONG_TERM_MEMORIES" not in prompt_args


def _monthly_llm_result(text, call_id="call-123", finish_reason="stop"):
    from obsidian_ai_hub.utils.llm_client import LLMResult

    return LLMResult(text=text, call_id=call_id, finish_reason=finish_reason)


@pytest.mark.parametrize(
    "text,finish_reason",
    [
        ('{"summary": "ok", "progress": ["a"]}', "length"),
        ('{"summary": "cut off in progress", "progress": ["a",', "stop"),
        ('["not", "an", "object"]', "stop"),
        (json.dumps({"summary": "   "}), "stop"),
    ],
)
def test_monthly_failures_do_not_persist(
    mock_config, test_memory_db_path, text, finish_reason
):
    from obsidian_ai_hub.summerize_month import get_monthly_structured_record

    with (
        patch(
            "obsidian_ai_hub.summerize_month.prompt.render_prompt",
            return_value="Rendered Prompt",
        ),
        patch(
            "obsidian_ai_hub.summerize_month.llm_client.generate_llm_response_detailed",
            return_value=_monthly_llm_result(
                text, call_id="call-xyz", finish_reason=finish_reason
            ),
        ),
    ):
        with pytest.raises(ValueError) as excinfo:
            get_monthly_structured_record(datetime(2024, 10, 1), [])
    assert "call-xyz" in str(excinfo.value)

    conn = memory.get_db_connection()
    try:
        assert store.get_summary_by_period("month", "2024-10", conn=conn) is None
    finally:
        conn.close()


def test_monthly_truncated_does_not_overwrite_existing(
    mock_config, test_memory_db_path
):
    conn = memory.get_db_connection()
    try:
        store.upsert_summary(
            {
                "period_type": "month",
                "period_key": "2024-10",
                "period_start": "2024-10-01",
                "period_end": "2024-10-31",
                "generated_at": "2024-10-01T22:00:00",
                "summary": "Existing summary",
                "keywords": [],
                "mood": None,
                "sleep_raw": None,
                "sleep_hours": None,
                "topics": [],
                "projects": [],
                "people": [],
                "items": [],
            },
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()

    with (
        patch(
            "obsidian_ai_hub.summerize_month.prompt.render_prompt",
            return_value="Rendered Prompt",
        ),
        patch(
            "obsidian_ai_hub.summerize_month.llm_client.generate_llm_response_detailed",
            return_value=_monthly_llm_result(
                '{"summary": "cut', call_id="call-trunc", finish_reason="length"
            ),
        ),
    ):
        with pytest.raises(ValueError):
            summerize_month.summarize_month(datetime(2024, 10, 1))

    conn = memory.get_db_connection()
    try:
        row = store.get_summary_by_period("month", "2024-10", conn=conn)
        assert row is not None
        assert row["summary"] == "Existing summary"
    finally:
        conn.close()
