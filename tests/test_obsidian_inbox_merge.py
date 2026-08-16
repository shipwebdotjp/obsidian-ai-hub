from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub import obsidian_inbox_merge


def test_build_classification_prompt_includes_current_date():
    rendered = obsidian_inbox_merge._build_classification_prompt(
        "今月20日に歯医者",
        effective_dt=datetime(2026, 8, 16, 9, 0, 0),
    )

    assert "基準日（今日）は `2026/8/16` です" in rendered
    assert "今月20日に歯医者" in rendered


def test_build_classification_prompt_requires_date_only_reminder_due_date():
    rendered = obsidian_inbox_merge._build_classification_prompt(
        "明日までに本を返す",
        effective_dt=datetime(2026, 8, 16, 9, 0, 0),
    )

    assert "期限の時刻が明示されない場合は `YYYY-MM-DD`" in rendered
    assert "時刻が明示される場合" in rendered
    assert "`YYYY-MM-DDTHH:MM:SS`" in rendered
    assert "開始時刻が不明なら `00:00:00` とする" in rendered


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


def test_merge_content_reminder_registers_hitl_and_keeps_memo(
    tmp_path: Path, test_memory_db_path
):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    with (
        patch.object(
            obsidian_inbox_merge.llm_client,
            "generate_llm_response",
            return_value=(
                '{"category":"reminder","reminder":{'
                '"title":"本の返却","due_date":"2026-05-15T18:00:00"}}'
            ),
        ),
        patch.object(obsidian_inbox_merge.add_research_theme, "append_research_theme"),
    ):
        result = obsidian_inbox_merge.merge_content_into_daily_note(
            "明日までに本を返す", daily_file, "08:30"
        )

    assert result == "reminder"
    merged = daily_file.read_text(encoding="utf-8")
    assert "# Daily" in merged
    assert "## 📝メモ" in merged
    assert "- 08:30 [reminder] 明日までに本を返す" in merged

    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub.hitl.store import list_runs

    conn = get_db_connection()
    try:
        runs, _ = list_runs(conn=conn)
        reminder_runs = [
            r for r in runs if r["handler"] == "reminders.add_approved_reminder"
        ]
    finally:
        conn.close()
    assert len(reminder_runs) == 1
    assert reminder_runs[0]["status"] == "pending_user"


def test_repeated_reminder_merge_does_not_duplicate_approval_run(
    tmp_path: Path, test_memory_db_path
):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    with patch.object(
        obsidian_inbox_merge.llm_client,
        "generate_llm_response",
        return_value=(
            '{"category":"reminder","reminder":{'
            '"title":"本の返却","due_date":"2026-05-15T18:00:00"}}'
        ),
    ):
        obsidian_inbox_merge.merge_content_into_daily_note(
            "明日までに本を返す", daily_file, "08:30"
        )
        obsidian_inbox_merge.merge_content_into_daily_note(
            "明日までに本を返す", daily_file, "08:30"
        )

    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub.hitl.store import list_runs

    conn = get_db_connection()
    try:
        runs, _ = list_runs(conn=conn)
        reminder_runs = [
            r for r in runs if r["handler"] == "reminders.add_approved_reminder"
        ]
    finally:
        conn.close()
    assert len(reminder_runs) == 1


def _count_reminder_runs() -> int:
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub.hitl.store import list_runs

    conn = get_db_connection()
    try:
        runs, _ = list_runs(conn=conn)
        reminder_runs = [
            r for r in runs if r["handler"] == "reminders.add_approved_reminder"
        ]
    finally:
        conn.close()
    return len(reminder_runs)


def test_merge_content_reminder_missing_title_falls_back_to_memo(
    tmp_path: Path, test_memory_db_path
):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    with patch.object(
        obsidian_inbox_merge.llm_client,
        "generate_llm_response",
        return_value=(
            '{"category":"reminder","reminder":{"due_date":"2026-05-15T18:00:00"}}'
        ),
    ):
        result = obsidian_inbox_merge.merge_content_into_daily_note(
            "明日までに本を返す", daily_file, "08:30"
        )

    assert result == "memo"
    merged = daily_file.read_text(encoding="utf-8")
    assert "[memo]" in merged
    assert _count_reminder_runs() == 0


def test_merge_content_reminder_invalid_due_date_falls_back_to_memo(
    tmp_path: Path, test_memory_db_path
):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    with patch.object(
        obsidian_inbox_merge.llm_client,
        "generate_llm_response",
        return_value=(
            '{"category":"reminder","reminder":{'
            '"title":"本の返却","due_date":"not-a-date"}}'
        ),
    ):
        result = obsidian_inbox_merge.merge_content_into_daily_note(
            "明日までに本を返す", daily_file, "08:30"
        )

    assert result == "memo"
    merged = daily_file.read_text(encoding="utf-8")
    assert "[memo]" in merged
    assert _count_reminder_runs() == 0


def test_merge_content_reminder_non_string_due_date_falls_back_to_memo(
    tmp_path: Path, test_memory_db_path
):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    with patch.object(
        obsidian_inbox_merge.llm_client,
        "generate_llm_response",
        return_value=(
            '{"category":"reminder","reminder":{"title":"本の返却","due_date":123}}'
        ),
    ):
        result = obsidian_inbox_merge.merge_content_into_daily_note(
            "明日までに本を返す", daily_file, "08:30"
        )

    assert result == "memo"
    merged = daily_file.read_text(encoding="utf-8")
    assert "[memo]" in merged
    assert _count_reminder_runs() == 0


def test_merge_content_reminder_empty_due_date_is_accepted(
    tmp_path: Path, test_memory_db_path
):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    with patch.object(
        obsidian_inbox_merge.llm_client,
        "generate_llm_response",
        return_value=(
            '{"category":"reminder","reminder":{"title":"本の返却","due_date":""}}'
        ),
    ):
        result = obsidian_inbox_merge.merge_content_into_daily_note(
            "明日までに本を返す", daily_file, "08:30"
        )

    assert result == "reminder"
    merged = daily_file.read_text(encoding="utf-8")
    assert "[reminder]" in merged
    assert _count_reminder_runs() == 1
