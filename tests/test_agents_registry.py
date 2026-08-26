import json
from unittest.mock import MagicMock, patch
import subprocess
import signal
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
        "project_search",
        "project_get",
        "skills",
        "run_shell",
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


def _seed_projects_for_registry():
    """Create confirmed projects and summary links for registry tests."""
    from obsidian_ai_hub.web import service, schemas
    from obsidian_ai_hub.summary import store as summary_store

    # Create three projects with different domain/status
    p1 = service.create_project(
        schemas.ProjectCreateRequest(display_name="AI Hub", domain="work", status="active", goal="AI Hub goal")
    )
    p2 = service.create_project(
        schemas.ProjectCreateRequest(display_name="Blog Project", domain="personal", status="active")
    )
    p3 = service.create_project(
        schemas.ProjectCreateRequest(display_name="AI Research", domain="work", status="paused")
    )
    # Special char project for LIKE escaping test
    p4 = service.create_project(
        schemas.ProjectCreateRequest(display_name="Test%Project", domain="work", status="active")
    )
    # Create a project with exact name "AI" for exact-priority test
    p5 = service.create_project(
        schemas.ProjectCreateRequest(display_name="AI", domain="work", status="active")
    )

    # Link summaries to p1 to give it higher summary_count
    for i in range(5):
        summary_store.upsert_summary(
            {
                "period_type": "day",
                "period_key": f"2026-08-{10+i:02d}",
                "summary": f"AI Hub day {i}",
                "project_ids": [p1["project_id"]],
            }
        )
    # One summary for p2
    summary_store.upsert_summary(
        {
            "period_type": "day",
            "period_key": "2026-08-20",
            "summary": "Blog day",
            "project_ids": [p2["project_id"]],
        }
    )
    return {"AI Hub": p1["project_id"], "Blog Project": p2["project_id"], "AI Research": p3["project_id"], "Test%Project": p4["project_id"], "AI": p5["project_id"]}


def test_project_search_basic():
    _seed_projects_for_registry()
    # substring match
    res = json.loads(registry.project_search.invoke({"query": "AI Hub", "limit": 10}))
    assert "projects" in res
    names = [p["display_name"] for p in res["projects"]]
    assert "AI Hub" in names
    assert "Blog Project" not in names

    # empty query returns all (at least 5)
    res2 = json.loads(registry.project_search.invoke({"query": "", "limit": 20}))
    assert len(res2["projects"]) >= 5

    # spaces-only query treated as empty
    res3 = json.loads(registry.project_search.invoke({"query": "   ", "limit": 20}))
    assert len(res3["projects"]) >= 5

    # no match
    res4 = json.loads(registry.project_search.invoke({"query": "存在しないXYZ", "limit": 10}))
    assert res4["projects"] == []

    # limit enforcement
    res5 = json.loads(registry.project_search.invoke({"query": "AI", "limit": 1}))
    assert len(res5["projects"]) == 1


def test_project_search_filters_and_excludes_candidates():
    from obsidian_ai_hub.database import get_db_connection

    _seed_projects_for_registry()
    # domain filter
    res = json.loads(registry.project_search.invoke({"query": "", "domain": "personal", "limit": 20}))
    assert all(p["domain"] == "personal" for p in res["projects"])
    assert any(p["display_name"] == "Blog Project" for p in res["projects"])
    assert not any(p["display_name"] == "AI Hub" for p in res["projects"])

    # status filter
    res2 = json.loads(registry.project_search.invoke({"query": "", "status": "paused", "limit": 20}))
    assert all(p["status"] == "paused" for p in res2["projects"])
    assert any(p["display_name"] == "AI Research" for p in res2["projects"])

    # candidates must NOT appear in project_search
    from obsidian_ai_hub.summary import store as summary_store

    summary_store.upsert_summary(
        {
            "period_type": "day",
            "period_key": "2026-08-21",
            "summary": "candidate test",
            "project_candidates": [{"name": "Candidate X", "domain": "work", "evidence": "test"}],
        }
    )
    res3 = json.loads(registry.project_search.invoke({"query": "Candidate", "limit": 10}))
    assert res3["projects"] == []


def test_project_search_exact_priority_and_wildcard_escape():
    _seed_projects_for_registry()
    # exact match "AI" should prioritize project named exactly "AI" over "AI Hub" despite higher summary_count
    res = json.loads(registry.project_search.invoke({"query": "AI", "limit": 10}))
    names = [p["display_name"] for p in res["projects"]]
    # "AI" must be first due to exact_priority
    assert names[0] == "AI"
    # LIKE wildcard escaping: query containing % should match only literal %
    res2 = json.loads(registry.project_search.invoke({"query": "Test%", "limit": 10}))
    assert any(p["display_name"] == "Test%Project" for p in res2["projects"])
    # query without % should NOT match Test%Project via wildcard
    res3 = json.loads(registry.project_search.invoke({"query": "TestProject", "limit": 10}))
    assert not any(p["display_name"] == "Test%Project" for p in res3["projects"])


def test_project_get_with_truncation_and_path():
    from obsidian_ai_hub.web import service, schemas
    from obsidian_ai_hub.summary import store as summary_store

    proj = service.create_project(
        schemas.ProjectCreateRequest(display_name="Truncate Proj", domain="work", status="active", project_path="projects/truncate")
    )
    pid = proj["project_id"]
    # Create 25 summaries linked to this project (period_start ordering is DESC)
    for i in range(25):
        # Use 2026-07-01 .. 2026-07-25
        day = f"2026-07-{i+1:02d}"
        summary_store.upsert_summary(
            {
                "period_type": "day",
                "period_key": day,
                "summary": f"day {i}",
                "project_ids": [pid],
            }
        )
    res = json.loads(registry.project_get.invoke({"project_id": pid}))
    assert res["display_name"] == "Truncate Proj"
    assert res["project_path"] == "projects/truncate"
    assert res["summary_count"] == 25
    assert len(res["summaries"]) == 20
    assert res["summaries_truncated"] is True
    # newest first: first entry should be 2026-07-25, last of truncated is 2026-07-06
    assert res["summaries"][0]["period_key"] == "2026-07-25"
    assert res["summaries"][-1]["period_key"] == "2026-07-06"

    # project without many summaries: no truncation
    proj2 = service.create_project(
        schemas.ProjectCreateRequest(display_name="Small Proj", domain="personal", status="active")
    )
    pid2 = proj2["project_id"]
    res2 = json.loads(registry.project_get.invoke({"project_id": pid2}))
    assert res2["summaries_truncated"] is False
    assert res2["summary_count"] == 0


def test_project_get_not_found():
    _seed_projects_for_registry()
    res = json.loads(registry.project_get.invoke({"project_id": 999999}))
    assert "error" in res


def test_project_get_validation():
    from pydantic import ValidationError

    # bool (and any non-int) should be rejected due to strict=True
    with pytest.raises(ValidationError):
        registry.project_get.invoke({"project_id": True})
    # non-numeric string must be rejected
    with pytest.raises(ValidationError):
        registry.project_get.invoke({"project_id": "abc"})


def test_run_shell_success():
    res_str = registry.run_shell.invoke({"command": "echo Hello Shell"})
    res = json.loads(res_str)
    assert res["exit_code"] == 0
    assert "Hello Shell" in res["stdout"]
    assert res["stderr"] == ""
    assert res["timeout"] is False


def test_run_shell_env_and_cwd():
    import os
    from obsidian_ai_hub.utils.config import BASE_DIR

    res_str = registry.run_shell.invoke({"command": "pwd"})
    res = json.loads(res_str)
    assert res["exit_code"] == 0
    assert str(BASE_DIR) in res["stdout"]

    os.environ["TEST_RUN_SHELL_ENV_VAR"] = "shell_test_value"
    try:
        res_env_str = registry.run_shell.invoke({"command": "echo $TEST_RUN_SHELL_ENV_VAR"})
        res_env = json.loads(res_env_str)
        assert "shell_test_value" in res_env["stdout"]
    finally:
        os.environ.pop("TEST_RUN_SHELL_ENV_VAR", None)


def test_run_shell_truncation():
    # Generate stdout and stderr longer than 20,000 characters
    cmd = "python3 -c 'import sys; print(\"A\" * 25000); print(\"B\" * 25000, file=sys.stderr)'"
    res_str = registry.run_shell.invoke({"command": cmd})
    res = json.loads(res_str)
    assert res["exit_code"] == 0
    assert len(res["stdout"]) < 21000
    assert res["stdout"].startswith("A" * 20000)
    assert res["stdout"].endswith("\n...(truncated)")
    assert len(res["stderr"]) < 21000
    assert res["stderr"].startswith("B" * 20000)
    assert res["stderr"].endswith("\n...(truncated)")


def test_run_shell_timeout():
    with patch("obsidian_ai_hub.agents.registry.os.killpg") as mock_killpg:
        # We mock communication timeout on Popen
        with patch("subprocess.Popen") as mock_popen_cls:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.communicate.side_effect = [
                subprocess.TimeoutExpired(cmd="sleep 100", timeout=600),
                ("partial stdout", "partial stderr"),
            ]
            mock_popen_cls.return_value = mock_proc

            res_str = registry.run_shell.invoke({"command": "sleep 100"})
            res = json.loads(res_str)
            assert res["exit_code"] == -1
            assert res["timeout"] is True
            assert res["stdout"] == "partial stdout"
            assert res["stderr"] == "partial stderr"
            mock_killpg.assert_called_once_with(12345, signal.SIGKILL)
