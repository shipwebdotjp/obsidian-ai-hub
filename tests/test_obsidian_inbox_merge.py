from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub import obsidian_inbox_merge


def test_merge_content_into_daily_note_completes_successfully(tmp_path: Path):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    with (
        patch.object(
            obsidian_inbox_merge.llm_client,
            "generate_llm_response",
            return_value='{"category":"memo"}',
        ),
        patch.object(obsidian_inbox_merge.add_research_theme, "append_research_theme"),
    ):
        result = obsidian_inbox_merge.merge_content_into_daily_note(
            "some content", daily_file, "08:30"
        )

    assert result is not None
    assert "some content" in daily_file.read_text(encoding="utf-8")


def test_merge_content_with_location_completes_successfully(tmp_path: Path):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📍今日の移動\n", encoding="utf-8")
    content = "---\nlocation: home\n---\nmoving"

    with patch.object(
        obsidian_inbox_merge.config, "LOCATION_MAP", {"home": "Home"}, create=True
    ):
        result = obsidian_inbox_merge.merge_content_into_daily_note(
            content, daily_file, "07:45"
        )

    assert result == "location"
    assert "07:45" in daily_file.read_text(encoding="utf-8")
    assert "Home" in daily_file.read_text(encoding="utf-8")


def test_merge_content_calendar_registers_hitl_and_keeps_memo(
    tmp_path: Path, test_memory_db_path
):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    with (
        patch.object(
            obsidian_inbox_merge.llm_client,
            "generate_llm_response",
            return_value=(
                '{"category":"calendar","calendar_event":{'
                '"title":"歯医者","start_time":"2026-05-10T14:00:00",'
                '"end_time":"2026-05-10T15:00:00","location":"駅前クリニック"}}'
            ),
        ),
        patch.object(obsidian_inbox_merge.add_research_theme, "append_research_theme"),
    ):
        result = obsidian_inbox_merge.merge_content_into_daily_note(
            "明日14時から歯医者", daily_file, "08:30"
        )

    assert result == "calendar"
    merged = daily_file.read_text(encoding="utf-8")
    assert "[calendar]" in merged
    assert "明日14時から歯医者" in merged

    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub.hitl.store import list_runs

    conn = get_db_connection()
    try:
        runs, _ = list_runs(conn=conn)
        calendar_runs = [
            r for r in runs if r["handler"] == "calendar.add_approved_event"
        ]
    finally:
        conn.close()
    assert len(calendar_runs) == 1
    assert calendar_runs[0]["status"] == "pending_user"


def test_repeated_calendar_merge_does_not_duplicate_approval_run(
    tmp_path: Path, test_memory_db_path
):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    with patch.object(
        obsidian_inbox_merge.llm_client,
        "generate_llm_response",
        return_value=(
            '{"category":"calendar","calendar_event":{'
            '"title":"歯医者","start_time":"2026-05-10T14:00:00",'
            '"end_time":"2026-05-10T15:00:00","location":"駅前クリニック"}}'
        ),
    ):
        obsidian_inbox_merge.merge_content_into_daily_note(
            "明日14時から歯医者", daily_file, "08:30"
        )
        obsidian_inbox_merge.merge_content_into_daily_note(
            "明日14時から歯医者", daily_file, "08:30"
        )

    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub.hitl.store import list_runs

    conn = get_db_connection()
    try:
        runs, _ = list_runs(conn=conn)
        calendar_runs = [
            r for r in runs if r["handler"] == "calendar.add_approved_event"
        ]
    finally:
        conn.close()
    assert len(calendar_runs) == 1
