"""Tests for weekly memory extraction from Web-chat agent conversations."""

import json
import sqlite3
import uuid
from datetime import timedelta, timezone
from unittest.mock import patch

import pytest

from obsidian_ai_hub import database, memory
from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils import config as app_config

JST = timezone(timedelta(hours=9))
WEEK_DATE = "2026-07-13"  # Monday; window 2026-07-13 .. 2026-07-19 JST
UTC_IN_WEEK = "2026-07-14T01:00:00+00:00"  # 2026-07-14 10:00 JST


def _make_agent(name: str) -> dict:
    return agent_store.create_agent(
        name=f"{name} {uuid.uuid4().hex[:8]}", system_prompt="Prompt"
    )


def _make_chat_session(agent_id: str, title: str = "雑談") -> str:
    return agent_store.create_session(agent_id, title=title, source="chat")[
        "session_id"
    ]


def _make_source_session(agent_id: str, source: str, title: str) -> str:
    return agent_store.create_session(agent_id, title=title, source=source)[
        "session_id"
    ]


def _make_null_source_session(agent_id: str, title: str) -> str:
    """Insert a session as if it predated migration v65 (source stays NULL)."""
    session_id = f"asess_{uuid.uuid4().hex[:12]}"
    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO agent_sessions (session_id, agent_id, title, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, agent_id, title, UTC_IN_WEEK, UTC_IN_WEEK),
            )
    finally:
        conn.close()
    return session_id


def _insert_message(
    session_id: str, role: str, content: str, created_at: str = UTC_IN_WEEK
) -> str:
    message_id = f"amsg_{uuid.uuid4().hex[:12]}"
    conn = get_db_connection()
    try:
        with conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            conn.execute(
                "INSERT INTO agent_messages (message_id, session_id, sequence, role, content, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, session_id, row[0], role, content, created_at),
            )
    finally:
        conn.close()
    return message_id


def _candidate(memory_key: str, content: str, path: str, quote: str) -> dict:
    return {
        "kind": "preference",
        "memory_key": memory_key,
        "content": content,
        "topics": ["その他"],
        "tags": ["文体"],
        "evidence": [
            {"path": path, "quote": quote, "observed_at": "2026-07-14"}
        ],
        "valid_from": "2026-07-14",
        "stability": "stable",
        "extraction_confidence": 0.9,
    }


def test_extract_agent_conversation_memories_requires_user_evidence():
    agent = _make_agent("Conv Agent")
    chat_sid = _make_chat_session(agent["agent_id"])
    task_sid = _make_source_session(agent["agent_id"], "task", "Task step")
    workflow_sid = _make_source_session(
        agent["agent_id"], "workflow", "Workflow arun_x"
    )
    legacy_sid = _make_null_source_session(agent["agent_id"], "古い会話")

    user_mid = _insert_message(chat_sid, "user", "AIの返答は簡潔な日本語にしてほしい")
    assistant_mid = _insert_message(chat_sid, "assistant", "承知しました。以後簡潔にします。")
    task_user_mid = _insert_message(task_sid, "user", "タスク指示の本文")
    workflow_user_mid = _insert_message(workflow_sid, "user", "ワークフロー入力の本文")
    legacy_user_mid = _insert_message(legacy_sid, "user", "導入前セッションの本文")

    response = json.dumps(
        [
            _candidate(
                "chat-user-evidence",
                "簡潔な日本語を好む",
                f"agent://sessions/{chat_sid}/messages/{user_mid}",
                "簡潔な日本語にしてほしい",
            ),
            _candidate(
                "assistant-evidence",
                "アシスタント由来の候補",
                f"agent://sessions/{chat_sid}/messages/{assistant_mid}",
                "以後簡潔にします",
            ),
            _candidate(
                "task-evidence",
                "タスク由来の候補",
                f"agent://sessions/{task_sid}/messages/{task_user_mid}",
                "タスク指示の本文",
            ),
            _candidate(
                "workflow-evidence",
                "ワークフロー由来の候補",
                f"agent://sessions/{workflow_sid}/messages/{workflow_user_mid}",
                "ワークフロー入力の本文",
            ),
            _candidate(
                "legacy-evidence",
                "導入前セッション由来の候補",
                f"agent://sessions/{legacy_sid}/messages/{legacy_user_mid}",
                "導入前セッションの本文",
            ),
            _candidate(
                "quote-mismatch",
                "引用不一致の候補",
                f"agent://sessions/{chat_sid}/messages/{user_mid}",
                "ログに存在しない引用",
            ),
        ],
        ensure_ascii=False,
    )

    with patch(
        "obsidian_ai_hub.memory.llm_client.generate_llm_response"
    ) as mock_llm:
        mock_llm.return_value = response
        candidates = memory.extract_agent_conversation_memories(WEEK_DATE)

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["memory_key"] == "chat-user-evidence"
    assert cand["evidence"] == [
        {
            "path": f"agent://sessions/{chat_sid}/messages/{user_mid}",
            "quote": "簡潔な日本語にしてほしい",
            "observed_at": "2026-07-14",
        }
    ]
    assert cand["provenance"]["extraction_method"] == "weekly_agent_conversation_llm"

    prompt = mock_llm.call_args.kwargs["prompt"]
    assert "AIの返答は簡潔な日本語にしてほしい" in prompt
    assert "承知しました。以後簡潔にします。" in prompt
    assert "タスク指示の本文" not in prompt
    assert "ワークフロー入力の本文" not in prompt
    assert "導入前セッションの本文" not in prompt

    saved = memory.load_all_memories()
    assert len(saved) == 1
    assert saved[0]["memory_id"] == cand["memory_id"]


def test_extract_agent_conversation_memories_marks_messages_processed():
    agent = _make_agent("Once Agent")
    chat_sid = _make_chat_session(agent["agent_id"])
    user_mid = _insert_message(chat_sid, "user", "毎朝30分走る習慣がある")
    assistant_mid = _insert_message(chat_sid, "assistant", "いい習慣ですね。")

    response = json.dumps(
        [
            _candidate(
                "habit",
                "毎朝30分走る",
                f"agent://sessions/{chat_sid}/messages/{user_mid}",
                "毎朝30分走る",
            )
        ],
        ensure_ascii=False,
    )

    with patch(
        "obsidian_ai_hub.memory.llm_client.generate_llm_response"
    ) as mock_llm:
        mock_llm.return_value = response
        first = memory.extract_agent_conversation_memories(WEEK_DATE)
        second = memory.extract_agent_conversation_memories(WEEK_DATE)

    assert len(first) == 1
    assert second == []
    assert mock_llm.call_count == 1

    conn = get_db_connection()
    try:
        logged = {
            row[0]
            for row in conn.execute(
                "SELECT message_id FROM agent_message_extraction_logs"
            ).fetchall()
        }
    finally:
        conn.close()
    assert logged == {user_mid, assistant_mid}


def test_extract_agent_conversation_memories_rejects_existing_candidate_content():
    agent = _make_agent("Dup Agent")
    chat_sid = _make_chat_session(agent["agent_id"])
    user_mid = _insert_message(chat_sid, "user", "静かな場所で作業するのが好き")

    existing = {
        "schema_version": 1,
        "memory_id": "mem_existing_candidate",
        "status": "candidate",
        "kind": "preference",
        "memory_key": "quiet-place",
        "content": "静かな場所で作業するのが好き",
        "topics": ["その他"],
        "tags": [],
        "evidence": [],
        "valid_from": "2026-07-13",
        "stability": "tentative",
        "created_at": "2026-07-13T10:00:00+09:00",
        "updated_at": "2026-07-13T10:00:00+09:00",
    }
    memory.save_all_memories([existing])

    response = json.dumps(
        [
            _candidate(
                "quiet-place",
                "静かな場所で作業するのが好き",
                f"agent://sessions/{chat_sid}/messages/{user_mid}",
                "静かな場所で作業するのが好き",
            )
        ],
        ensure_ascii=False,
    )

    with patch(
        "obsidian_ai_hub.memory.llm_client.generate_llm_response"
    ) as mock_llm:
        mock_llm.return_value = response
        candidates = memory.extract_agent_conversation_memories(WEEK_DATE)

    assert [c["status"] for c in candidates] == ["rejected"]


def test_load_weekly_agent_messages_groups_context_and_exclusions():
    agent = _make_agent("Context Agent")
    chat_sid = _make_chat_session(agent["agent_id"], title="会話タイトル")
    task_sid = _make_source_session(agent["agent_id"], "task", "Task step")
    legacy_sid = _make_null_source_session(agent["agent_id"], "古い会話")

    user_mid = _insert_message(chat_sid, "user", "ユーザー発話")
    assistant_mid = _insert_message(chat_sid, "assistant", "アシスタント返答")
    _insert_message(chat_sid, "user", "")
    _insert_message(task_sid, "user", "タスク指示")
    _insert_message(legacy_sid, "user", "導入前の発話")

    week_start, week_end = memory._week_bounds(WEEK_DATE)
    sessions, included_ids = memory._load_weekly_agent_messages(week_start, week_end)

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == chat_sid
    assert sessions[0]["session_title"] == "会話タイトル"
    assert [(e["role"], e["message_id"]) for e in sessions[0]["entries"]] == [
        ("user", user_mid),
        ("assistant", assistant_mid),
    ]
    assert included_ids == [user_mid, assistant_mid]


def test_load_weekly_agent_messages_ignores_out_of_window_and_disabled(monkeypatch):
    agent = _make_agent("Window Agent")
    chat_sid = _make_chat_session(agent["agent_id"])
    _insert_message(chat_sid, "user", "先週の発話", created_at="2026-07-06T01:00:00+00:00")

    week_start, week_end = memory._week_bounds(WEEK_DATE)
    sessions, included_ids = memory._load_weekly_agent_messages(week_start, week_end)
    assert sessions == []
    assert included_ids == []

    _insert_message(chat_sid, "user", "今週の発話")
    monkeypatch.setattr(app_config, "MEMORY_AGENT_CONVERSATION_ENABLED", False)
    sessions, included_ids = memory._load_weekly_agent_messages(week_start, week_end)
    assert sessions == []
    assert included_ids == []

    with patch(
        "obsidian_ai_hub.memory.llm_client.generate_llm_response"
    ) as mock_llm:
        assert memory.extract_agent_conversation_memories(WEEK_DATE) == []
        mock_llm.assert_not_called()


def test_load_weekly_agent_messages_truncates_and_caps(monkeypatch):
    agent = _make_agent("Budget Agent")
    chat_sid = _make_chat_session(agent["agent_id"])
    long_user_mid = _insert_message(chat_sid, "user", "あ" * 20)
    _insert_message(chat_sid, "assistant", "い" * 20)

    monkeypatch.setattr(app_config, "MEMORY_AGENT_CONVERSATION_MAX_USER_CHARS", 5)
    monkeypatch.setattr(
        app_config, "MEMORY_AGENT_CONVERSATION_MAX_ASSISTANT_CHARS", 0
    )
    monkeypatch.setattr(app_config, "MEMORY_AGENT_CONVERSATION_MAX_TOTAL_CHARS", 12)

    week_start, week_end = memory._week_bounds(WEEK_DATE)
    sessions, included_ids = memory._load_weekly_agent_messages(week_start, week_end)

    entries = sessions[0]["entries"]
    assert entries[0]["content"] == "あ" * 5 + "…"
    assert entries[0]["message_id"] == long_user_mid
    # The assistant entry (20 chars) exceeds the remaining budget and is skipped.
    assert [e["role"] for e in entries] == ["user"]
    assert included_ids == [long_user_mid]


def test_extract_memories_runs_agent_conversation_source():
    daily_dir = app_config.VAULT_PATH / "daily" / "2026" / "07"
    daily_dir.mkdir(parents=True, exist_ok=True)
    (daily_dir / "2026-07-13.md").write_text(
        "# 2026-07-13\n\n## 💡 今日の気づき・振り返り\n\n簡潔な応答が好き\n",
        encoding="utf-8",
    )

    agent = _make_agent("Wire Agent")
    chat_sid = _make_chat_session(agent["agent_id"])
    user_mid = _insert_message(chat_sid, "user", "海沿いの街に住んでいる")

    daily_response = (
        '[{"kind": "preference", "memory_key": "daily-key", "content": "簡潔な応答を好む",'
        ' "topics": ["その他"], "evidence": [{"path": "daily/2026/07/2026-07-13.md",'
        ' "quote": "簡潔な応答が好き", "observed_at": "2026-07-13"}],'
        ' "valid_from": "2026-07-13", "stability": "stable"}]'
    )
    conversation_response = json.dumps(
        [
            _candidate(
                "residence",
                "海沿いの街に住んでいる",
                f"agent://sessions/{chat_sid}/messages/{user_mid}",
                "海沿いの街に住んでいる",
            )
        ],
        ensure_ascii=False,
    )

    with patch(
        "obsidian_ai_hub.memory.llm_client.generate_llm_response"
    ) as mock_llm:
        mock_llm.side_effect = [daily_response, conversation_response]
        candidates = memory.extract_memories(WEEK_DATE)

    assert mock_llm.call_count == 2
    keys = {c["memory_key"] for c in candidates}
    assert keys == {"daily-key", "residence"}


def test_extract_memories_without_daily_notes_still_extracts_conversations():
    agent = _make_agent("No Notes Agent")
    chat_sid = _make_chat_session(agent["agent_id"])
    user_mid = _insert_message(chat_sid, "user", "週末は山に登るのが趣味")

    response = json.dumps(
        [
            _candidate(
                "hobby",
                "週末は山に登るのが趣味",
                f"agent://sessions/{chat_sid}/messages/{user_mid}",
                "週末は山に登るのが趣味",
            )
        ],
        ensure_ascii=False,
    )

    with patch(
        "obsidian_ai_hub.memory.llm_client.generate_llm_response"
    ) as mock_llm:
        mock_llm.return_value = response
        candidates = memory.extract_memories(WEEK_DATE)

    assert mock_llm.call_count == 1
    assert [c["memory_key"] for c in candidates] == ["hobby"]


def test_migration_v65_adds_source_and_extraction_logs(tmp_path):
    db_file = tmp_path / "v64.sqlite3"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("""
        CREATE TABLE agent_sessions (
            session_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    conn.execute("""
        CREATE TABLE agent_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
            UNIQUE(session_id, sequence)
        );
    """)
    conn.execute(
        "INSERT INTO agent_sessions VALUES ('s1', 'a1', '旧セッション', 't', 't');"
    )
    conn.execute(
        "INSERT INTO agent_messages VALUES ('m1', 's1', 1, 'user', '本文', 't');"
    )
    conn.execute("PRAGMA user_version = 64;")
    conn.commit()

    try:
        database.run_migration_v65(conn)

        assert conn.execute("PRAGMA user_version").fetchone()[0] == 65
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(agent_sessions);")
        }
        assert "source" in columns
        # Pre-existing sessions stay NULL so they are never extracted.
        assert (
            conn.execute("SELECT source FROM agent_sessions WHERE session_id='s1'").fetchone()[
                0
            ]
            is None
        )
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "agent_message_extraction_logs" in tables

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE agent_sessions SET source='bogus' WHERE session_id='s1';")

        conn.execute(
            "INSERT INTO agent_message_extraction_logs (message_id, processed_at) VALUES ('m1', 't');"
        )
        conn.execute("DELETE FROM agent_messages WHERE message_id = 'm1';")
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM agent_message_extraction_logs"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_create_session_source_validation_and_default():
    agent = _make_agent("Source Agent")

    with pytest.raises(ValueError, match="session source"):
        agent_store.create_session(agent["agent_id"], source="bogus")

    default_session = agent_store.create_session(agent["agent_id"])
    assert default_session["source"] == "chat"

    task_session = agent_store.create_session(
        agent["agent_id"], title="Task", source="task"
    )
    assert task_session["source"] == "task"
    assert agent_store.get_session(task_session["session_id"])["source"] == "task"
