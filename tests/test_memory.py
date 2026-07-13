# ruff: noqa: E402
import sys
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

    # SQLite DB temporary path configuration
    db_file = tmp_path / "memory.sqlite3"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    return vault_path


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
    assert version == 1

    # Verify tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    assert "memories" in tables
    assert "memory_events" in tables

    # Verify indexes exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
    indexes = [row[0] for row in cursor.fetchall()]
    assert "idx_memories_status" in indexes
    assert "idx_memories_memory_key" in indexes
    assert "idx_memory_events_memory_id_occurred_at" in indexes

    conn.close()


def test_run_deduplication():
    # Setup some existing approved memories
    existing = [
        {
            "memory_id": "mem_001",
            "status": "approved",
            "kind": "preference",
            "memory_key": "response-style-concise",
            "content": "簡潔な日本語を好みます。"
        },
        {
            "memory_id": "mem_002",
            "status": "approved",
            "kind": "preference",
            "memory_key": "other-key",
            "content": "別の記憶内容です。"
        }
    ]

    # Candidate with duplicate key and same normalized content
    cand1 = {
        "memory_key": "response-style-concise",
        "content": "簡潔な日本語を好みます。"
    }
    sug1 = memory.run_deduplication(cand1, existing, embedder=None)
    assert len(sug1) == 1
    assert sug1[0]["relation"] == "duplicate"
    assert sug1[0]["target_memory_id"] == "mem_001"

    # Candidate with duplicate key but different content (supersedes)
    cand2 = {
        "memory_key": "response-style-concise",
        "content": "より丁寧な日本語を好みます。"
    }
    sug2 = memory.run_deduplication(cand2, existing, embedder=None)
    assert len(sug2) == 1
    assert sug2[0]["relation"] == "supersedes"

    # Candidate with duplicate content but different key
    cand3 = {
        "memory_key": "unique-key",
        "content": "簡潔な日本語を好みます。"
    }
    sug3 = memory.run_deduplication(cand3, existing, embedder=None)
    assert len(sug3) == 1
    assert sug3[0]["relation"] == "duplicate"


def test_extract_memories(clean_memory_env):
    target_date = "2026-07-13"

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

    with patch("obsidian_ai_hub.memory.reader.get_daily_note_content") as mock_daily_note, \
         patch("obsidian_ai_hub.memory.llm_client.generate_llm_response") as mock_llm:

        mock_daily_note.return_value = "AIは簡潔に話してほしい"
        mock_llm.return_value = mock_llm_response

        candidates = memory.extract_memories(target_date)

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
            cursor.execute("SELECT * FROM memory_events WHERE memory_id = ?", (cand["memory_id"],))
            events = cursor.fetchall()
            assert len(events) == 1
            assert events[0]["event_type"] == "created"


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
        "updated_at": "2026-07-13T10:00:00+09:00"
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
        cursor.execute("SELECT event_type FROM memory_events WHERE memory_id = ?", (mem_id,))
        event_types = [r[0] for r in cursor.fetchall()]
        assert "rejected" in event_types

    # 2. Approve review
    # Update candidate status back to "candidate" for test purposes
    with memory.get_db_connection() as conn:
        conn.execute("UPDATE memories SET status = 'candidate' WHERE memory_id = ?", (mem_id,))

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
        "stability": "stable"
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
        "stability": "stable"
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
        "stability": "stable"
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
    assert any(x["memory_id"] == "mem_3" and x["reason"] == "not_yet_valid" for x in context_pack["excluded"])


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
        "valid_from": "2026-07-01"
    }
    memory.save_all_memories([m1])

    # Mock daily notes and schedule views
    with patch("obsidian_ai_hub.make_today_target.reader") as mock_reader, \
         patch("obsidian_ai_hub.make_today_target.extracter") as mock_extracter, \
         patch("obsidian_ai_hub.make_today_target.llm_client") as mock_llm:

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
        # Invalid: memory-extract without date
        with pytest.raises(SystemExit):
            monkeypatch.setattr(sys, "argv", ["main.py", "--memory-extract"])
            main.main()
        mock_err.assert_called()

        # Invalid: memory-review without action
        with pytest.raises(SystemExit):
            monkeypatch.setattr(sys, "argv", ["main.py", "--memory-review", "--id", "mem_1"])
            main.main()

        # Invalid: memory-review with multiple actions
        with pytest.raises(SystemExit):
            monkeypatch.setattr(sys, "argv", ["main.py", "--memory-review", "--id", "mem_1", "--approve", "--reject"])
            main.main()

        # Invalid: edit action without content
        with pytest.raises(SystemExit):
            monkeypatch.setattr(sys, "argv", ["main.py", "--memory-review", "--id", "mem_1", "--edit"])
            main.main()


def test_config_fallback_ordering(tmp_path, monkeypatch):
    # 1. Environment variable has highest precedence
    env_path = tmp_path / "env_db.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(env_path))

    # Mock config.yml value to differ
    config_path = tmp_path / "config_db.sqlite3"
    monkeypatch.setattr(config, "yaml_config", {"memory": {"sqlite_path": str(config_path)}})

    # Real evaluation of _env_or_config
    val = config._env_or_config("MEMORY_SQLITE_PATH", "memory", "sqlite_path")
    assert val == str(env_path)

    # 2. config.yml takes precedence if env var is not set
    monkeypatch.delenv("MEMORY_SQLITE_PATH", raising=False)
    val = config._env_or_config("MEMORY_SQLITE_PATH", "memory", "sqlite_path")
    assert val == str(config_path)

    # 3. Default path is used if neither is set
    monkeypatch.setattr(config, "yaml_config", {})
    val = config._env_or_config("MEMORY_SQLITE_PATH", "memory", "sqlite_path")
    assert val is None
