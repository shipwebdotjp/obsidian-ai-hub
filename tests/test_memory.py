# ruff: noqa: E402
# ruff: noqa: E402
import sys
from datetime import datetime
from unittest.mock import MagicMock

# Mock macOS-specific modules before importing obsidian_ai_hub to prevent ModuleNotFoundError on Linux/CI
mock_modules = {
    "EventKit": MagicMock(),
    "AppKit": MagicMock(),
    "objc": MagicMock(),
    "Foundation": MagicMock(),
    "ApplicationServices": MagicMock(),
    "atomacos": MagicMock(),
    "Quartz": MagicMock(),
    "Vision": MagicMock(),
    "Cocoa": MagicMock(),
}
for name, m in mock_modules.items():
    sys.modules[name] = m

from unittest.mock import patch
import pytest

from obsidian_ai_hub import memory, main, make_today_target
from obsidian_ai_hub.utils import config


@pytest.fixture
def clean_memory_env(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault"
    vault_path.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "VAULT_PATH", vault_path)

    # Re-register subpaths
    copilot_dir = vault_path / "copilot"
    copilot_dir.mkdir(exist_ok=True)
    (copilot_dir / "core").mkdir(exist_ok=True)
    (copilot_dir / "memory").mkdir(exist_ok=True)
    (copilot_dir / "eval").mkdir(exist_ok=True)

    activity_dir = vault_path / "activity"
    activity_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "ACTIVITY_PATH", activity_dir)
    monkeypatch.setattr(config, "DAILY_PATH", vault_path / "daily")

    # SQLite DB temporary path configuration
    db_file = tmp_path / "memory.sqlite3"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    return vault_path


def test_normalize_stability_valid():
    assert memory.normalize_stability("stable") == "stable"
    assert memory.normalize_stability("tentative") == "tentative"
    assert memory.normalize_stability("explicitly_settled") == "explicitly_settled"


def test_normalize_stability_coerces_invalid():
    assert memory.normalize_stability("bogus") == "tentative"
    assert memory.normalize_stability("") == "tentative"
    assert memory.normalize_stability(123) == "tentative"
    assert memory.normalize_stability(None) == "tentative"
    assert memory.normalize_stability("stable", default="stable") == "stable"
    assert memory.normalize_stability("", default="stable") == "stable"


def test_normalize_content():
    text1 = " 　日本語   TEST  "
    # NFKC normalizes wide spaces to standard space, stripping deletes all whitespace
    norm = memory.normalize_content(text1)
    assert norm == "日本語test"


def test_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    assert memory.cosine_similarity(v1, v2) == pytest.approx(1.0)
    assert memory.cosine_similarity(v1, v3) == pytest.approx(0.0)


def test_id_generation():
    mem_id = memory.generate_memory_id("2026-07-13")
    assert mem_id.startswith("mem_20260713_")
    assert len(mem_id) == len("mem_20260713_") + 6

    evt_id = memory.generate_event_id()
    assert evt_id.startswith("evt_")
    assert len(evt_id) == 16


def test_memory_week_bounds():
    week_start, week_end = memory._week_bounds("2026-07-15")
    assert week_start.strftime("%Y-%m-%d") == "2026-07-13"
    assert week_end.strftime("%Y-%m-%d") == "2026-07-19"

    week_start, week_end = memory._week_bounds(now=datetime(2026, 7, 13, 12, 0))
    assert week_start.strftime("%Y-%m-%d") == "2026-07-06"
    assert week_end.strftime("%Y-%m-%d") == "2026-07-12"


def test_db_initialization_and_indexes(clean_memory_env):
    db_path = config.MEMORY_SQLITE_PATH
    assert not db_path.exists()

    # Getting connection should initialize DB
    conn = memory.get_db_connection()
    assert db_path.exists()

    # Query schema version
    cursor = conn.cursor()
    cursor.execute("PRAGMA user_version;")
    version = cursor.fetchone()[0]
    assert version == 9

    # Verify tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert "memories" in tables
    assert "memory_events" in tables
    assert "activity_logs" in tables
    assert "summaries" in tables
    assert "summary_items" in tables
    assert "topics" in tables
    assert "projects" in tables
    assert "people" in tables
    assert "person_candidates" in tables
    assert "summary_person_candidates" in tables
    assert "summary_person_assignments" in tables

    # Verify indexes exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_memories_status" in indexes
    assert "idx_memories_memory_key" in indexes
    assert "idx_memory_events_memory_id_occurred_at" in indexes
    assert "idx_activity_logs_date_occurred" in indexes
    assert "idx_summaries_period" in indexes
    assert "idx_spc_summary_id" in indexes
    assert "idx_pc_normalized_name" in indexes
    assert "idx_spa_normalized_name" in indexes

    conn.close()


def test_run_deduplication():
    # Setup some existing approved memories
    existing = [
        {
            "memory_id": "mem_001",
            "status": "approved",
            "kind": "preference",
            "memory_key": "response-style-concise",
            "content": "簡潔な日本語を好みます。",
        },
        {
            "memory_id": "mem_002",
            "status": "approved",
            "kind": "preference",
            "memory_key": "other-key",
            "content": "別の記憶内容です。",
        },
    ]

    # Candidate with duplicate key and same normalized content
    cand1 = {
        "memory_key": "response-style-concise",
        "content": "簡潔な日本語を好みます。",
    }
    sug1 = memory.run_deduplication(cand1, existing, embedder=None)
    assert len(sug1) == 1
    assert sug1[0]["relation"] == "duplicate"
    assert sug1[0]["target_memory_id"] == "mem_001"

    # Candidate with duplicate key but different content (supersedes)
    cand2 = {
        "memory_key": "response-style-concise",
        "content": "より丁寧な日本語を好みます。",
    }
    sug2 = memory.run_deduplication(cand2, existing, embedder=None)
    assert len(sug2) == 1
    assert sug2[0]["relation"] == "supersedes"

    # Candidate with duplicate content but different key
    cand3 = {"memory_key": "unique-key", "content": "簡潔な日本語を好みます。"}
    sug3 = memory.run_deduplication(cand3, existing, embedder=None)
    assert len(sug3) == 1
    assert sug3[0]["relation"] == "duplicate"


def test_extract_memories(clean_memory_env):
    week_date = "2026-07-13"
    daily_dir = clean_memory_env / "daily" / "2026" / "07"
    daily_dir.mkdir(parents=True)
    (daily_dir / "2026-07-13.md").write_text(
        "# 2026-07-13\n\n"
        "## 💡 今日の気づき・振り返り\n\nAIは簡潔に話してほしい\n\n"
        "## 📝メモ\n\n追加のメモ\n\n"
        "## AIによる要約\n\n要約本文は入力しない\n",
        encoding="utf-8",
    )

    from obsidian_ai_hub.summary import store as summary_store

    summary_store.upsert_summary(
        {
            "period_type": "day",
            "period_key": week_date,
            "period_start": week_date,
            "period_end": week_date,
            "generated_at": "2026-07-13T22:00:00",
            "summary": "簡潔な応答を望んだ",
            "keywords": [],
            "mood": "good",
            "sleep_raw": "7h",
            "sleep_hours": 7.0,
            "topics": ["その他"],
            "projects": [],
            "people": [],
            "items": [],
        }
    )

    # Mock LLM response for extraction
    mock_llm_response = """
    [
      {
        "kind": "preference",
        "memory_key": "response-style-concise",
        "content": "簡潔な表現を好む",
        "topics": ["その他"],
        "tags": ["文体"],
        "evidence": [
          {
            "path": "daily/2026/07/2026-07-13.md",
            "quote": "AIは簡潔に話してほしい",
            "observed_at": "2026-07-13"
          }
        ],
        "valid_from": "2026-07-13",
        "stability": "stable",
        "extraction_confidence": 0.95
      }
    ]
    """

    with patch("obsidian_ai_hub.memory.llm_client.generate_llm_response") as mock_llm:
        mock_llm.return_value = mock_llm_response

        candidates = memory.extract_memories(week_date)

        assert len(candidates) == 1
        cand = candidates[0]
        assert cand["status"] == "candidate"
        assert cand["memory_key"] == "response-style-concise"
        assert cand["content"] == "簡潔な表現を好む"

        # Verify saved to SQLite database
        mems = memory.load_all_memories()
        assert len(mems) == 1
        assert mems[0]["memory_id"] == cand["memory_id"]

        # Verify events table has "created" event
        with memory.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM memory_events WHERE memory_id = ?", (cand["memory_id"],)
            )
            events = cursor.fetchall()
            assert len(events) == 1
        assert events[0]["event_type"] == "created"

        rendered_prompt = mock_llm.call_args.kwargs["prompt"]
        assert "AIは簡潔に話してほしい" in rendered_prompt
        assert "追加のメモ" in rendered_prompt
        assert "要約本文は入力しない" not in rendered_prompt
        assert "簡潔な応答を望んだ" in rendered_prompt


def test_load_daily_structured_record_from_sqlite(clean_memory_env):
    target_date = datetime(2026, 7, 13)
    from obsidian_ai_hub.summary import store as summary_store

    summary_store.upsert_summary(
        {
            "period_type": "day",
            "period_key": "2026-07-13",
            "period_start": "2026-07-13",
            "period_end": "2026-07-13",
            "generated_at": "2026-07-13T22:00:00",
            "summary": "SQLite summary",
            "keywords": ["sqlite"],
            "mood": "good",
            "sleep_raw": "7h",
            "sleep_hours": 7.0,
            "topics": ["LLM・AI活用"],
            "projects": ["Project A"],
            "people": [{"name": "Alice", "note": "met"}],
            "items": [
                {"kind": "highlights", "body": "Highlight", "display_order": 0},
                {"kind": "activities", "body": "Activity", "display_order": 0},
            ],
        }
    )

    record = memory._load_daily_structured_record(target_date)
    assert record["date"] == "2026-07-13"
    assert record["summary"] == "SQLite summary"
    assert record["mood"] == "good"
    assert record["sleep"] == "7h"
    assert record["topics"] == ["LLM・AI活用"]
    assert record["highlights"] == ["Highlight"]
    assert record["activities"] == ["Activity"]
    assert record["people"] == [{"name": "Alice", "note": "met"}]

    missing = memory._load_daily_structured_record(datetime(1900, 1, 1))
    assert missing == {}


def test_extract_memories_skips_week_without_notes(clean_memory_env):
    with patch("obsidian_ai_hub.memory.llm_client.generate_llm_response") as mock_llm:
        assert memory.extract_memories("2026-07-13") == []
        mock_llm.assert_not_called()


def test_review_memory(clean_memory_env):
    # Setup candidate memory
    mem_id = "mem_20260713_test1"
    cand = {
        "schema_version": 1,
        "memory_id": mem_id,
        "status": "candidate",
        "kind": "preference",
        "memory_key": "test-key",
        "content": "テスト内容",
        "topics": ["その他"],
        "tags": [],
        "evidence": [],
        "valid_from": "2026-07-13",
        "stability": "stable",
        "created_at": "2026-07-13T10:00:00+09:00",
        "updated_at": "2026-07-13T10:00:00+09:00",
    }
    memory.save_all_memories([cand])

    # 1. Reject review
    success = memory.review_memory(mem_id, "reject")
    assert success is True
    mems = memory.load_all_memories()
    assert mems[0]["status"] == "rejected"

    # Verify event logged
    with memory.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT event_type FROM memory_events WHERE memory_id = ?", (mem_id,)
        )
        event_types = [r[0] for r in cursor.fetchall()]
        assert "rejected" in event_types

    # 2. Approve review
    # Reset candidate status back to "candidate" through the public API
    mems = memory.load_all_memories()
    mems[0]["status"] = "candidate"
    memory.save_all_memories(mems)

    success = memory.review_memory(mem_id, "approve")
    assert success is True
    mems = memory.load_all_memories()
    assert mems[0]["status"] == "approved"

    # Verify approved.md exists and contains content with revised heading
    app_md_path = memory.get_approved_memories_path()
    assert app_md_path.exists()
    md_content = app_md_path.read_text(encoding="utf-8")
    assert "テスト内容" in md_content

    # 3. Edit review
    success = memory.review_memory(mem_id, "edit", "新しい編集された内容")
    assert success is True
    mems = memory.load_all_memories()
    assert mems[0]["content"] == "新しい編集された内容"
    assert mems[0]["status"] == "approved"


def test_compile_context(clean_memory_env, monkeypatch):
    monkeypatch.setattr(config, "MEMORY_CONTEXT_MAX_TOKENS", 100)

    # Setup approved memory
    m1 = {
        "memory_id": "mem_1",
        "status": "approved",
        "kind": "preference",
        "memory_key": "key-1",
        "content": "簡潔な話し方を好む",
        "valid_from": "2026-07-01",
        "extraction_confidence": 0.95,
        "stability": "stable",
    }
    # Expired memory
    m2 = {
        "memory_id": "mem_2",
        "status": "approved",
        "kind": "preference",
        "memory_key": "key-2",
        "content": "一時的な古い記憶",
        "valid_from": "2026-07-01",
        "valid_until": "2026-07-10",
        "extraction_confidence": 0.90,
        "stability": "stable",
    }
    # Future memory
    m3 = {
        "memory_id": "mem_3",
        "status": "approved",
        "kind": "preference",
        "memory_key": "key-3",
        "content": "未来の記憶",
        "valid_from": "2026-08-01",
        "extraction_confidence": 0.90,
        "stability": "stable",
    }

    memory.save_all_memories([m1, m2, m3])

    context_pack = memory.compile_context("make-target")

    # Only m1 should be compiled
    assert context_pack["used_memory_ids"] == ["mem_1"]
    assert "簡潔な話し方を好む" in context_pack["context"]

    # Verify m2 transitioned to expired
    mems = memory.load_all_memories()
    m2_saved = next(x for x in mems if x["memory_id"] == "mem_2")
    assert m2_saved["status"] == "expired"

    # Future memory m3 should be in excluded list as not_yet_valid
    assert any(
        x["memory_id"] == "mem_3" and x["reason"] == "not_yet_valid"
        for x in context_pack["excluded"]
    )


def test_make_today_target_integration(clean_memory_env):
    # Setup substantial guidelines and mock memory compilation
    vault_path = clean_memory_env
    copilot_dir = vault_path / "copilot"
    ai_readme = copilot_dir / "AI_README.md"
    ai_readme.write_text("""---
updated_at: 2026-07-13
---
# AI README
実質的な指示内容。
""")

    m1 = {
        "memory_id": "mem_1",
        "status": "approved",
        "kind": "preference",
        "memory_key": "key-1",
        "content": "具体的な記憶",
        "valid_from": "2026-07-01",
    }
    memory.save_all_memories([m1])

    # Mock daily notes and schedule views
    with (
        patch("obsidian_ai_hub.make_today_target.reader") as mock_reader,
        patch("obsidian_ai_hub.make_today_target.extracter") as mock_extracter,
        patch("obsidian_ai_hub.make_today_target.llm_client") as mock_llm,
    ):
        mock_reader.get_daily_note_content.return_value = "今日の目標\nExisting content"
        mock_reader.get_daily_note_path.return_value = vault_path / "daily_note.md"
        mock_extracter.get_subheader_view.return_value = "Mock Schedule"
        mock_extracter.get_frontmatter_value.return_value = "5"

        mock_llm.generate_llm_response.return_value = "Generated target"

        # Mock prompt file
        prompt_file = vault_path / "make_today_target.md"
        prompt_file.write_text("【今日の予定】\n${todays_schedule}\n")
        with patch.object(config, "MAKE_TODAY_TARGET_PROMPT_PATH", prompt_file):
            make_today_target.main()

            # Verify compile context was called and long term memory was injected
            mock_llm.generate_llm_response.assert_called_once()
            called_kwargs = mock_llm.generate_llm_response.call_args[1]
            assert "system_prompt" in called_kwargs
            assert "実質的な指示内容" in called_kwargs["system_prompt"]
            assert "具体的な記憶" in called_kwargs["prompt"]


def test_cli_args_parsing_validation(monkeypatch):
    # Use patch to mock standard system exit during ArgumentParser.error
    with patch("argparse.ArgumentParser.error", side_effect=SystemExit) as mock_err:
        # Invalid: --week without memory extraction
        with pytest.raises(SystemExit):
            monkeypatch.setattr(sys, "argv", ["main.py", "--week", "2026-07-13"])
            main.main()
        mock_err.assert_called()

        # --date is no longer accepted for memory extraction
        with pytest.raises(SystemExit):
            monkeypatch.setattr(
                sys, "argv", ["main.py", "--memory-extract", "--date", "2026-07-13"]
            )
            main.main()

        # An explicit week is passed through to weekly memory extraction.
        with patch(
            "obsidian_ai_hub.memory.extract_memories", return_value=[]
        ) as mock_extract:
            monkeypatch.setattr(
                sys, "argv", ["main.py", "--memory-extract", "--week", "2026-07-13"]
            )
            main.main()
            mock_extract.assert_called_once_with("2026-07-13")

        # Invalid: memory-review without action
        with pytest.raises(SystemExit):
            monkeypatch.setattr(
                sys, "argv", ["main.py", "--memory-review", "--id", "mem_1"]
            )
            main.main()

        # Invalid: memory-review with multiple actions
        with pytest.raises(SystemExit):
            monkeypatch.setattr(
                sys,
                "argv",
                [
                    "main.py",
                    "--memory-review",
                    "--id",
                    "mem_1",
                    "--approve",
                    "--reject",
                ],
            )
            main.main()

        # Invalid: edit action without content
        with pytest.raises(SystemExit):
            monkeypatch.setattr(
                sys, "argv", ["main.py", "--memory-review", "--id", "mem_1", "--edit"]
            )
            main.main()


def test_config_fallback_ordering(tmp_path, monkeypatch):
    # 1. Environment variable has highest precedence
    env_path = tmp_path / "env_db.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(env_path))

    # Mock config.yml value to differ
    config_path = tmp_path / "config_db.sqlite3"
    monkeypatch.setattr(
        config, "yaml_config", {"memory": {"sqlite_path": str(config_path)}}
    )

    # Real evaluation of _env_or_config
    val = config._env_or_config("MEMORY_SQLITE_PATH", "memory", "sqlite_path")
    assert val == str(env_path)

    # 2. config.yml takes precedence if env var is not set
    monkeypatch.delenv("MEMORY_SQLITE_PATH", raising=False)
    val = config._env_or_config("MEMORY_SQLITE_PATH", "memory", "sqlite_path")
    assert val == str(config_path)

    # 3. _env_or_config returns None when neither env var nor config.yml value is set
    monkeypatch.setattr(config, "yaml_config", {})
    val = config._env_or_config("MEMORY_SQLITE_PATH", "memory", "sqlite_path")
    assert val is None


def test_delete_memory(clean_memory_env):
    m = {
        "memory_id": "mem_del_test",
        "status": "candidate",
        "kind": "preference",
        "memory_key": "del-key",
        "content": "削除テスト",
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    memory.save_all_memories([m])

    mems = memory.load_all_memories()
    assert len(mems) == 1

    result = memory.delete_memory("mem_del_test")
    assert result["found"] is True
    assert result["deleted"] is True
    assert result["memory"]["content"] == "削除テスト"

    mems = memory.load_all_memories()
    assert len(mems) == 0

    with memory.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM memory_events WHERE memory_id = ?", ("mem_del_test",)
        )
        assert cursor.fetchone()[0] == 0


def test_delete_memory_not_found(clean_memory_env):
    result = memory.delete_memory("mem_nonexistent")
    assert result["found"] is False
    assert result["deleted"] is False
    assert result["memory"] is None


def test_delete_memory_with_events(clean_memory_env):
    m = {
        "memory_id": "mem_evt_del",
        "status": "approved",
        "kind": "preference",
        "memory_key": "evt-del-key",
        "content": "イベント付き削除テスト",
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    memory.save_all_memories([m])

    memory.log_memory_event(
        event_type="approved",
        memory_id="mem_evt_del",
        previous_status="candidate",
        new_status="approved",
        reason="承認テスト",
    )
    memory.log_memory_event(
        event_type="rejected",
        memory_id="mem_evt_del",
        previous_status="approved",
        new_status="rejected",
        reason="却下テスト",
    )

    with memory.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM memory_events WHERE memory_id = ?", ("mem_evt_del",)
        )
        assert cursor.fetchone()[0] == 2

    result = memory.delete_memory("mem_evt_del")
    assert result["found"] is True
    assert result["deleted"] is True
    assert result["events_deleted"] == 2

    with memory.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM memory_events WHERE memory_id = ?", ("mem_evt_del",)
        )
        assert cursor.fetchone()[0] == 0


def test_delete_memory_prunes_dedup_suggestions(clean_memory_env):
    approved = {
        "memory_id": "mem_approved_1",
        "status": "approved",
        "kind": "preference",
        "memory_key": "approved-key",
        "content": "承認済み内容",
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    candidate_with_suggestion = {
        "memory_id": "mem_candidate_ref",
        "status": "candidate",
        "kind": "preference",
        "memory_key": "cand-key",
        "content": "候補の内容",
        "dedup_suggestions": [
            {
                "target_memory_id": "mem_approved_1",
                "relation": "duplicate",
                "score": 0.95,
            },
        ],
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    another_candidate = {
        "memory_id": "mem_other_cand",
        "status": "candidate",
        "kind": "preference",
        "memory_key": "other-key",
        "content": "別の候補",
        "dedup_suggestions": [
            {
                "target_memory_id": "mem_approved_1",
                "relation": "duplicate",
                "score": 0.90,
            },
            {
                "target_memory_id": "mem_unrelated",
                "relation": "duplicate",
                "score": 0.80,
            },
        ],
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    no_suggestion = {
        "memory_id": "mem_no_sug",
        "status": "candidate",
        "kind": "preference",
        "memory_key": "no-sug-key",
        "content": "提案なし",
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }

    memory.save_all_memories(
        [approved, candidate_with_suggestion, another_candidate, no_suggestion]
    )

    result = memory.delete_memory("mem_approved_1")
    assert result["found"] is True
    assert result["deleted"] is True

    remaining = memory.load_all_memories()
    remaining_map = {m["memory_id"]: m for m in remaining}

    # mem_candidate_ref should have empty dedup_suggestions (now None)
    ref = remaining_map.get("mem_candidate_ref")
    assert ref is not None
    assert ref.get("dedup_suggestions") is None or ref["dedup_suggestions"] == []

    # mem_other_cand should have the unrelated suggestion left
    other = remaining_map.get("mem_other_cand")
    assert other is not None
    remaining_sugs = other.get("dedup_suggestions") or []
    assert len(remaining_sugs) == 1
    assert remaining_sugs[0]["target_memory_id"] == "mem_unrelated"

    # no_suggestion should remain untouched
    no_ref = remaining_map.get("mem_no_sug")
    assert no_ref is not None
    assert no_ref.get("dedup_suggestions") is None or no_ref["dedup_suggestions"] == []


def test_delete_memory_reprojects_approved(clean_memory_env):
    approved_mem = {
        "memory_id": "mem_to_remove",
        "status": "approved",
        "kind": "preference",
        "memory_key": "remove-key",
        "content": "削除される承認済み",
        "evidence": [],
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    keep_mem = {
        "memory_id": "mem_keep",
        "status": "approved",
        "kind": "fact",
        "memory_key": "keep-key",
        "content": "残る承認済み",
        "evidence": [],
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    memory.save_all_memories([approved_mem, keep_mem])

    approved_md = memory.get_approved_memories_path()
    memory.project_approved_memories()
    assert approved_md.exists()
    content_before = approved_md.read_text(encoding="utf-8")
    assert "削除される承認済み" in content_before
    assert "残る承認済み" in content_before

    r = memory.delete_memory("mem_to_remove")
    assert r["found"] is True
    assert r["deleted"] is True

    content_after = approved_md.read_text(encoding="utf-8")
    assert "削除される承認済み" not in content_after
    assert "残る承認済み" in content_after


def test_batch_delete_memories(clean_memory_env):
    memories = [
        {
            "memory_id": "mem_batch_1",
            "status": "candidate",
            "kind": "preference",
            "memory_key": "b1",
            "content": "一括1",
        },
        {
            "memory_id": "mem_batch_2",
            "status": "candidate",
            "kind": "preference",
            "memory_key": "b2",
            "content": "一括2",
        },
        {
            "memory_id": "mem_batch_3",
            "status": "approved",
            "kind": "preference",
            "memory_key": "b3",
            "content": "一括3",
            "evidence": [],
        },
    ]
    for m in memories:
        m["created_at"] = "2026-07-14T10:00:00+09:00"
        m["updated_at"] = "2026-07-14T10:00:00+09:00"
    memory.save_all_memories(memories)

    # Pre-create approved.md
    memory.project_approved_memories()
    approved_md = memory.get_approved_memories_path()
    assert approved_md.exists()
    assert "一括3" in approved_md.read_text(encoding="utf-8")

    memory.log_memory_event(
        event_type="created",
        memory_id="mem_batch_1",
        previous_status=None,
        new_status="candidate",
    )

    # Delete 3 IDs, one of which doesn't exist
    result = memory.batch_delete_memories(
        ["mem_batch_1", "mem_batch_2", "mem_batch_nonexistent"]
    )
    assert set(result["deleted"]) == {"mem_batch_1", "mem_batch_2"}
    assert result["not_found"] == ["mem_batch_nonexistent"]
    assert result["events_deleted"] == 1  # only mem_batch_1 had events

    remaining = memory.load_all_memories()
    remaining_ids = [m["memory_id"] for m in remaining]
    assert "mem_batch_1" not in remaining_ids
    assert "mem_batch_2" not in remaining_ids
    assert "mem_batch_3" in remaining_ids

    # Verify approved.md still valid (no approved memories were deleted)
    assert approved_md.exists()
    content = approved_md.read_text(encoding="utf-8")
    assert "一括3" in content
    assert "一括1" not in content


def test_batch_delete_memories_empty(clean_memory_env):
    result = memory.batch_delete_memories([])
    assert result["deleted"] == []
    assert result["not_found"] == []
    assert result["events_deleted"] == 0


def test_superseded_editing_restrictions(clean_memory_env):
    m = {
        "memory_id": "mem_superseded_test",
        "status": "superseded",
        "kind": "preference",
        "memory_key": "restricted-key",
        "content": "置換済みの記憶",
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    memory.save_all_memories([m])

    # Cannot review superseded memory
    success = memory.review_memory("mem_superseded_test", "approve")
    assert success is False

    # Cannot edit superseded memory
    with pytest.raises(ValueError, match="Cannot edit a superseded memory"):
        memory.update_memory_fields(
            "mem_superseded_test", {"content": "編集された内容"}
        )


def test_resolve_memory_merge_existing(clean_memory_env):
    target = {
        "memory_id": "mem_existing_target",
        "status": "approved",
        "kind": "preference",
        "memory_key": "target-key",
        "content": "マージされる既存の記憶内容",
        "topics": ["その他"],
        "tags": ["タグ1"],
        "evidence": [{"path": "note1.md", "quote": "引用1"}],
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    cand = {
        "memory_id": "mem_cand_to_merge",
        "status": "candidate",
        "kind": "preference",
        "memory_key": "target-key",
        "content": "追加の記憶内容",
        "topics": ["開発"],
        "tags": ["タグ2"],
        "evidence": [{"path": "note2.md", "quote": "引用2"}],
        "dedup_suggestions": [
            {"target_memory_id": "mem_existing_target", "relation": "duplicate"}
        ],
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    memory.save_all_memories([target, cand])

    # Perform resolve_memory with merge_existing action
    new_cand, new_target = memory.resolve_memory(
        candidate_id="mem_cand_to_merge",
        action="merge_existing",
        target_memory_id="mem_existing_target",
        integrated_content="既存の記憶内容と追加内容を統合した文章",
    )

    assert new_cand["status"] == "rejected"
    assert new_target["status"] == "approved"
    assert new_target["content"] == "既存の記憶内容と追加内容を統合した文章"
    assert "開発" in new_target["topics"]
    assert "その他" in new_target["topics"]
    assert "タグ1" in new_target["tags"]
    assert "タグ2" in new_target["tags"]
    assert len(new_target["evidence"]) == 2

    # Verify event logs
    events_cand = memory.get_memory_events("mem_cand_to_merge")
    assert len(events_cand) == 1
    assert events_cand[0]["event_type"] == "rejected"

    events_target = memory.get_memory_events("mem_existing_target")
    assert len(events_target) == 1
    assert events_target[0]["event_type"] == "edited"


def test_resolve_memory_supersede_existing(clean_memory_env):
    target = {
        "memory_id": "mem_existing_target",
        "status": "approved",
        "kind": "preference",
        "memory_key": "target-key",
        "content": "置換される古い記憶内容",
        "valid_from": "2026-07-01",
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    cand = {
        "memory_id": "mem_cand_to_supersede",
        "status": "candidate",
        "kind": "preference",
        "memory_key": "different-key",  # test key unification
        "content": "新しい最新の記憶内容",
        "valid_from": "2026-07-15",
        "dedup_suggestions": [
            {"target_memory_id": "mem_existing_target", "relation": "supersedes"}
        ],
        "created_at": "2026-07-14T10:00:00+09:00",
        "updated_at": "2026-07-14T10:00:00+09:00",
    }
    memory.save_all_memories([target, cand])

    # Validation: switch_date must be strictly after target valid_from
    with pytest.raises(ValueError, match="must be strictly after existing valid_from"):
        memory.resolve_memory(
            candidate_id="mem_cand_to_supersede",
            action="supersede_existing",
            target_memory_id="mem_existing_target",
            switch_date="2026-06-30",  # before 2026-07-01
        )

    # Validation: switch_date equal to target valid_from must be rejected too
    with pytest.raises(ValueError, match="must be strictly after existing valid_from"):
        memory.resolve_memory(
            candidate_id="mem_cand_to_supersede",
            action="supersede_existing",
            target_memory_id="mem_existing_target",
            switch_date="2026-07-01",  # completely equal to 2026-07-01
        )

    # Valid resolution
    new_cand, new_target = memory.resolve_memory(
        candidate_id="mem_cand_to_supersede",
        action="supersede_existing",
        target_memory_id="mem_existing_target",
        switch_date="2026-07-15",
    )

    assert new_target["status"] == "superseded"
    assert new_target["valid_until"] == "2026-07-14"

    assert new_cand["status"] == "approved"
    assert new_cand["valid_from"] == "2026-07-15"
    assert new_cand["supersedes"] == "mem_existing_target"
    assert new_cand["memory_key"] == "target-key"  # unified to old memory_key

    # Check event logs
    events_target = memory.get_memory_events("mem_existing_target")
    assert len(events_target) == 1
    assert events_target[0]["event_type"] == "superseded"
    assert events_target[0]["changes"]["superseded_by"] == "mem_cand_to_supersede"

    events_cand = memory.get_memory_events("mem_cand_to_supersede")
    assert len(events_cand) == 1
    assert events_cand[0]["event_type"] == "approved"
    assert events_cand[0]["changes"]["supersedes"]["after"] == "mem_existing_target"


def test_extract_memories_with_dedup_assessment(clean_memory_env):
    week_date = "2026-07-13"
    daily_dir = clean_memory_env / "daily" / "2026" / "07"
    daily_dir.mkdir(parents=True)
    (daily_dir / "2026-07-13.md").write_text(
        "# 2026-07-13\n\n"
        "## 💡 今日の気づき・振り返り\n\nAIは簡潔に話してほしい\n\n"
        "## 📝メモ\n\n追加のメモ\n\n",
        encoding="utf-8",
    )

    # Pre-populate an approved memory to trigger deduplication
    existing_approved = {
        "memory_id": "mem_target_001",
        "status": "approved",
        "kind": "preference",
        "memory_key": "response-style-concise",
        "content": "既存の簡潔な話し方の好み",
        "created_at": "2026-07-12T10:00:00+09:00",
    }
    memory.save_all_memories([existing_approved])

    # Mock candidate extraction LLM response
    mock_extract_response = """
    [
      {
        "kind": "preference",
        "memory_key": "response-style-concise",
        "content": "簡潔な表現を好む",
        "topics": ["その他"],
        "tags": ["文体"],
        "evidence": [
          {"path": "daily/2026/07/2026-07-13.md", "quote": "AIは簡潔に話してほしい", "observed_at": "2026-07-13"}
        ],
        "valid_from": "2026-07-13",
        "stability": "stable",
        "extraction_confidence": 0.95
      }
    ]
    """

    # Mock dedup assessment LLM response
    mock_dedup_response = """
    [
      {
        "candidate_id": "mem_20260713_fixed",
        "decision": "merge",
        "target_memory_id": "mem_target_001",
        "reason": "既存の好みの内容をより具体化・精緻化しているためマージを提案",
        "integrated_content": "簡潔で自然な日本語の表現を好む。過度な励まし表現を避ける。"
      }
    ]
    """

    with (
        patch("obsidian_ai_hub.memory.llm_client.generate_llm_response") as mock_llm,
        patch(
            "obsidian_ai_hub.memory.generate_memory_id",
            return_value="mem_20260713_fixed",
        ),
    ):

        def fake_llm_response(*args, **kwargs):
            prompt_str = kwargs.get("prompt", "")
            if "対象期間" in prompt_str:
                return mock_extract_response
            else:
                return mock_dedup_response

        mock_llm.side_effect = fake_llm_response

        candidates = memory.extract_memories(week_date)

        assert len(candidates) == 1
        cand = candidates[0]
        assert cand["status"] == "candidate"
        assert cand["dedup_assessment"]["decision"] == "merge"
        assert cand["dedup_assessment"]["target_memory_id"] == "mem_target_001"
        assert (
            cand["dedup_assessment"]["integrated_content"]
            == "簡潔で自然な日本語の表現を好む。過度な励まし表現を避ける。"
        )
