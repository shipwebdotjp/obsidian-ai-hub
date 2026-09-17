import json
from datetime import date
from unittest.mock import patch
import pytest

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.research import capabilities, db


def test_research_context_snapshot():
    snapshot = capabilities.get_research_context_snapshot()
    assert isinstance(snapshot, dict)
    assert "daily_notes" in snapshot
    assert "latest_weekly_note" in snapshot
    assert "recent_activities" in snapshot
    assert "existing_themes" in snapshot
    assert "recent_feedback" in snapshot


def test_research_context_snapshot_prioritizes_decision_material():
    from obsidian_ai_hub.utils import reader

    today = date.today()
    path = reader.get_daily_note_path(today)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntitle: daily\n---\n## \n- [ ]\n活動: Task Agentを実装した\n",
        encoding="utf-8",
    )
    # Rejected feedback must be listed before approved feedback.
    conn = get_db_connection()
    try:
        approved = db.create_theme(theme="承認済みテーマ", status="approved", conn=conn)
        rejected = db.create_theme(theme="却下テーマ", status="rejected", conn=conn)
        conn.commit()
    finally:
        conn.close()
    db.set_theme_feedback(approved["theme_id"], status="approved", decision="approved")
    db.set_theme_feedback(
        rejected["theme_id"],
        status="rejected",
        decision="rejected",
        reason="duplicate",
    )

    snapshot = capabilities.get_research_context_snapshot()

    # Decision material comes first so the runtime history gist keeps it.
    assert list(snapshot.keys())[:3] == [
        "recent_activities",
        "existing_themes",
        "recent_feedback",
    ]
    decisions = [item["feedback_decision"] for item in snapshot["recent_feedback"]]
    assert decisions[:2] == ["rejected", "approved"]

    daily = [
        note
        for note in snapshot["daily_notes"]
        if note["date"] == today.strftime("%Y-%m-%d")
    ]
    assert daily
    content = daily[0]["content"]
    assert "title:" not in content
    assert "[ ]" not in content
    assert "Task Agentを実装した" in content


def test_periodic_note_read_excludes_empty_template():
    res = capabilities.read_periodic_note("day", "2000-01-01")
    assert res["content"] == ""
    assert res["truncated"] is False



def test_research_theme_history_search():
    conn = get_db_connection()
    try:
        db.create_theme(
            theme="量子コンピューティングの進展",
            direction="量子アルゴリズムの動向",
            kind="deep",
            why_now="論文発表増加",
            status="approved",
            conn=conn,
        )
        db.create_theme(
            theme="生成AIの業務活用",
            direction="社内LLMの構築",
            kind="explore",
            why_now="生産性向上",
            status="candidate",
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()

    # Search with query
    res1 = capabilities.search_research_theme_history(query="量子", limit=10)
    assert len(res1) == 1
    assert res1[0]["theme"] == "量子コンピューティングの進展"

    # Search with status filter
    res2 = capabilities.search_research_theme_history(status="candidate", limit=10)
    assert any(t["theme"] == "生成AIの業務活用" for t in res2)
    assert not any(t["theme"] == "量子コンピューティングの進展" for t in res2)


def test_activity_search_no_screenshots():
    conn = get_db_connection()
    try:
        today_str = date.today().strftime("%Y-%m-%d")
        conn.execute(
            """
            INSERT INTO activity_logs (
                activity_id, activity_date, occurred_at, app_name, window_title,
                summary, category, keywords, screenshots
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "act_test_001",
                today_str,
                f"{today_str}T10:00:00",
                "VSCode",
                "index.py - VSCode",
                "Task Agentの機能実装を検討",
                "開発",
                json.dumps(["Task", "Agent"]),
                json.dumps(["/path/to/screenshot.png"]),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    res = capabilities.search_activities(query="Task Agent", limit=10)
    assert len(res) >= 1
    item = res[0]
    assert item["summary"] == "Task Agentの機能実装を検討"
    assert "screenshots" not in item  # Screenshots are excluded per spec


def test_periodic_note_read():
    today_str = date.today().strftime("%Y-%m-%d")
    res_day = capabilities.read_periodic_note("day", today_str)
    assert res_day["period_type"] == "day"
    assert res_day["reference_date"] == today_str
    assert "content" in res_day
    assert "relative_path" in res_day

    res_week = capabilities.read_periodic_note("week", today_str)
    assert res_week["period_type"] == "week"
    assert "content" in res_week

    with pytest.raises(ValueError):
        capabilities.read_periodic_note("invalid_type", today_str)


def test_agent_conversation_search():
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO agents (agent_id, name, system_prompt, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("ag_test_001", "テストAgent", "sys prompt", "2026-09-01T00:00:00", "2026-09-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO agent_sessions (session_id, agent_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("asess_001", "ag_test_001", "セッション1", "2026-09-01T00:00:00", "2026-09-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO agent_messages (message_id, session_id, sequence, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("amsg_001", "asess_001", 1, "user", "分散システムの整合性モデルについて教えてください", "2026-09-01T10:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    # Empty query raises error
    with pytest.raises(ValueError):
        capabilities.search_agent_conversations("")

    # Valid query
    res = capabilities.search_agent_conversations("分散システム")
    assert len(res) == 1
    assert res[0]["session_id"] == "asess_001"
    assert res[0]["agent_id"] == "ag_test_001"
    assert "分散システム" in res[0]["excerpt"]


def test_coding_history_search():
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO projects (project_id, display_name, normalized_name, domain, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (101, "テストProject", "テストProject", "work", "active", "2026-09-01T00:00:00", "2026-09-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO coding_sessions (session_id, project_id, backend, repo_path, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("cses_001", 101, "direct_cli", "/tmp/repo", "セッション1", "2026-09-01T00:00:00", "2026-09-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO coding_messages (message_id, session_id, sequence, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("cmsg_001", "cses_001", 1, "user", "WebGPUによるアクセラレーション実装", "2026-09-01T10:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError):
        capabilities.search_coding_history("")

    res = capabilities.search_coding_history("WebGPU")
    assert len(res) == 1
    assert res[0]["session_id"] == "cses_001"
    assert res[0]["project_id"] == 101
    assert "WebGPU" in res[0]["excerpt"]


def test_propose_research_theme_handler_validation_and_idempotency():
    # Validation error for blank theme
    err = capabilities.propose_research_theme_handler(theme="   ")
    assert "error" in err

    # Validation error for long theme (>80 chars)
    long_theme = "あ" * 81
    err2 = capabilities.propose_research_theme_handler(theme=long_theme)
    assert "error" in err2

    # Validation error for long direction (>140 chars)
    long_dir = "い" * 141
    err3 = capabilities.propose_research_theme_handler(
        theme="Valid Theme", direction=long_dir
    )
    assert "error" in err3

    # Successful proposal with fake notification
    with patch("obsidian_ai_hub.line_notification.notify_research_suggestion"):
        trusted_ctx = {"task_id": "task_idempotency_001"}
        res1 = capabilities.propose_research_theme_handler(
            theme="エッジAIにおける量子化技術",
            direction="8bit量子化とモデル軽量化",
            kind="explore",
            why_now="エッジ端末普及に伴う需要増加",
            confidence=0.9,
            trusted_ctx=trusted_ctx,
        )
        assert res1["status"] in ("candidate", "duplicate")
        assert "theme_id" in res1
        theme_id = res1["theme_id"]

        # Call again with same task_id context
        res2 = capabilities.propose_research_theme_handler(
            theme="エッジAIにおける量子化技術",
            direction="8bit量子化とモデル軽量化",
            kind="explore",
            why_now="エッジ端末普及に伴う需要増加",
            confidence=0.9,
            trusted_ctx=trusted_ctx,
        )
        assert res2["status"] == "already_proposed"
        assert res2["theme_id"] == theme_id


def test_propose_research_theme_handler_persists_project_id():
    err = capabilities.propose_research_theme_handler(theme="PJ", project_id=-1)
    assert "error" in err

    with (
        patch("obsidian_ai_hub.line_notification.notify_research_suggestion"),
        patch(
            "obsidian_ai_hub.research.dedup.run_dedup_review",
            return_value={"decision": "new", "related_ids": [], "reason": None},
        ),
    ):
        res = capabilities.propose_research_theme_handler(
            theme="プロジェクト固有の設計判断ログ",
            project_id=42,
            trusted_ctx={"session_id": "sess_proj_001"},
        )

    assert res["status"] == "candidate"
    theme = db.get_theme(res["theme_id"])
    assert theme["project_id"] == 42
