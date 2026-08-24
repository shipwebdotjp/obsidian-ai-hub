import json
from unittest.mock import patch
import pytest
from langchain_core.tools import BaseTool

from obsidian_ai_hub.agents import registry
from obsidian_ai_hub.hitl.store import get_run


def test_list_available_tools():
    tools = registry.list_available_tools()
    tool_ids = [t["tool_id"] for t in tools]
    expected_ids = {
        "web_search",
        "web_extract",
        "vault_search",
        "vault_read_file",
        "calendar_read",
        "reminders_read",
        "calendar_create_proposal",
        "reminder_create_proposal",
        "memory_search",
        "memory_propose",
        "people_search",
        "people_get",
    }
    # Order is not contractual; assert membership instead.
    assert set(tool_ids) == expected_ids


def test_resolve_tools():
    # Deduplication and filtering unknown tools
    resolved = registry.resolve_tools(
        ["web_search", "web_search", "unknown_tool", "calendar_read"]
    )
    names = [t.name for t in resolved]
    assert len(resolved) == 2
    assert "web_search" in names
    assert "calendar_read" in names


def test_resolve_tools_returns_core_tools_and_excludes_direct_apple_writes():
    resolved = registry.resolve_tools(
        ["vault_search", "add_calendar_event", "add_reminder"]
    )

    assert [tool.name for tool in resolved] == ["search_obsidian_vault"]
    assert all(isinstance(tool, BaseTool) for tool in resolved)


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


def _seed_people_for_registry():
    """Create PEOPLE_PATH note and DB people via summaries for registry tests."""
    from obsidian_ai_hub.utils import config as app_config
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub.summary import store as summary_store

    # conftest autouse fixtures (_filesystem_sandbox, _isolate_sqlite_dbs)
    # already isolate PEOPLE_PATH and MEMORY_SQLITE_PATH per test.
    people_dir = app_config.PEOPLE_PATH
    people_dir.mkdir(parents=True, exist_ok=True)
    # Vault note for person linked via vault_id
    (people_dir / "yamada.md").write_text(
        """---
id: yamada-taro
name: 山田太郎
aliases:
  - ヤマダ
  - Taro
---
山田太郎さんについてのメモ。本文。
""",
        encoding="utf-8",
    )
    # Create confirmed people + summary links directly
    conn = get_db_connection()
    try:
        # Insert confirmed people first so upsert can link via vault/unlinked paths
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_yamada_registry_test", "山田太郎", "山田太郎", "yamada-taro"),
        )
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_sato_registry_test", "佐藤花子", "佐藤花子", None),
        )
        # alias for alias search test
        norm_yamada = summary_store.normalize_entity_name("ヤマダ")
        conn.execute(
            "INSERT OR IGNORE INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
            (norm_yamada, "peo_yamada_registry_test", "ヤマダ"),
        )
        conn.commit()
        # Now create summaries that link to these confirmed people
        summary_store.upsert_summary(
            {
                "period_type": "day",
                "period_key": "2026-08-10",
                "summary": "山田太郎と打合せ",
                "people": [{"name": "山田太郎", "note": "打合せメモ"}],
            },
            conn=conn,
        )
        summary_store.upsert_summary(
            {
                "period_type": "day",
                "period_key": "2026-08-11",
                "summary": "佐藤花子とランチ",
                "people": [{"name": "佐藤花子", "note": "ランチ"}],
            },
            conn=conn,
        )
        conn.commit()
        cur = conn.cursor()
        cur.execute("SELECT person_id, display_name FROM people ORDER BY display_name")
        ids = {r["display_name"]: r["person_id"] for r in cur.fetchall()}
        return ids
    finally:
        conn.close()


def test_people_search_basic():
    _seed_people_for_registry()
    # substring match on main name
    res = json.loads(registry.people_search.invoke({"query": "山田", "limit": 10}))
    assert "people" in res
    names = [p["display_name"] for p in res["people"]]
    assert "山田太郎" in names
    assert "佐藤花子" not in names
    # alias match
    res2 = json.loads(registry.people_search.invoke({"query": "ヤマダ", "limit": 10}))
    assert any(p["display_name"] == "山田太郎" for p in res2["people"])
    # no match
    res3 = json.loads(registry.people_search.invoke({"query": "存在しない名前XYZ", "limit": 10}))
    assert res3["people"] == []
    # empty query -> validation error
    res4 = json.loads(registry.people_search.invoke({"query": "   ", "limit": 5}))
    assert "error" in res4
    # limit enforcement (query '' already rejected, check limit 1)
    res5 = json.loads(registry.people_search.invoke({"query": "山田", "limit": 1}))
    assert len(res5["people"]) == 1


def test_people_search_excludes_candidates():
    from obsidian_ai_hub.database import get_db_connection

    _seed_people_for_registry()
    # Add an unresolved candidate that should NOT appear in people_search
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO person_candidates (candidate_id, display_name, normalized_name, status) VALUES (?, ?, ?, ?)",
            ("cand_001", "未解決太郎", "未解決太郎", "unresolved"),
        )
        conn.commit()
    finally:
        conn.close()
    res = json.loads(registry.people_search.invoke({"query": "未解決", "limit": 10}))
    assert res["people"] == []


def test_people_get_with_vault_note():
    ids = _seed_people_for_registry()
    taro_id = ids["山田太郎"]
    res = json.loads(registry.people_get.invoke({"person_id": taro_id}))
    assert res["display_name"] == "山田太郎"
    assert res["vault_id"] == "yamada-taro"
    assert "aliases" in res
    assert "summaries" in res
    assert "relation_counts" in res
    assert len(res["summaries"]) >= 1
    # vault_note enrichment
    assert "vault_note" in res
    assert res["vault_note"]["relative_path"].endswith("yamada.md")
    assert "山田太郎さんについてのメモ" in res["vault_note"]["content"]


def test_people_get_without_vault_id():
    ids = _seed_people_for_registry()
    hanako_id = ids["佐藤花子"]
    res = json.loads(registry.people_get.invoke({"person_id": hanako_id}))
    assert res["display_name"] == "佐藤花子"
    assert res["vault_id"] is None
    assert "vault_note" not in res


def test_people_get_not_found():
    _seed_people_for_registry()
    res = json.loads(registry.people_get.invoke({"person_id": "peo_nonexistent_123"}))
    assert "error" in res


def test_people_get_vault_note_missing_graceful():
    ids = _seed_people_for_registry()
    # Delete the vault file but keep DB vault_id
    from obsidian_ai_hub.utils import config as app_config

    p = app_config.PEOPLE_PATH / "yamada.md"
    if p.exists():
        p.unlink()
    taro_id = ids["山田太郎"]
    res = json.loads(registry.people_get.invoke({"person_id": taro_id}))
    # Should still return person detail, vault_note absent
    assert res["display_name"] == "山田太郎"
    assert "vault_note" not in res
