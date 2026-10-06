from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.memory.models import get_approved_memories_path
from obsidian_ai_hub.memory.maintenance import (
    parse_jst_date,
    is_obsolete,
    build_maintenance_groups,
    validate_proposals,
    run_maintenance_diagnosis,
    register_maintenance_hitl_run,
    apply_single_proposal,
    run_approved_maintenance,
)
from obsidian_ai_hub.hitl.dispatcher import dispatch_runs
from obsidian_ai_hub.hitl.service import submit_answer


def test_parse_jst_date():
    assert parse_jst_date("") is None
    assert parse_jst_date(None) is None

    # YYYY-MM-DD
    dt = parse_jst_date("2026-07-25")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 7
    assert dt.day == 25
    assert dt.tzinfo.utcoffset(None) == timedelta(hours=9)

    # ISO 8601 UTC
    dt_iso = parse_jst_date("2026-07-25T15:00:00Z")
    assert dt_iso is not None
    # 15:00 UTC is 00:00 JST on the next day (2026-07-26)
    assert dt_iso.year == 2026
    assert dt_iso.month == 7
    assert dt_iso.day == 26


def test_is_obsolete():
    base_date = datetime(2026, 7, 25, tzinfo=timezone(timedelta(hours=9)))

    # 1. Unexpired
    m_ok = {
        "valid_until": "2026-07-26",
        "evidence": [{"observed_at": "2026-07-20"}],
    }
    assert not is_obsolete(m_ok, base_date)

    # 2. valid_until expired (strictly before base_date)
    m_exp_vu = {"valid_until": "2026-07-24"}
    assert is_obsolete(m_exp_vu, base_date)

    # 3. review_due_at expired
    m_exp_rd = {"review_due_at": "2026-07-24"}
    assert is_obsolete(m_exp_rd, base_date)

    # 4. Old evidence >= 180 days ago
    m_old_ev = {
        "evidence": [{"observed_at": "2026-01-20"}],  # > 180 days from 2026-07-25
    }
    assert is_obsolete(m_old_ev, base_date)

    # 5. Invalid evidence date does not trigger obsolescence
    m_invalid_ev = {
        "evidence": [{"observed_at": "invalid-date"}],
    }
    assert not is_obsolete(m_invalid_ev, base_date)


def test_build_maintenance_groups_and_similarity():
    m1 = {
        "memory_id": "mem_1",
        "status": "approved",
        "kind": "preference",
        "memory_key": "user_preference",
        "content": "毎週日曜日に英会話をする",
    }
    m2 = {
        "memory_id": "mem_2",
        "status": "approved",
        "kind": "preference",
        "memory_key": "user_preference",
        "content": "日曜は英会話スクールに行く",
    }
    m3 = {
        "memory_id": "mem_3",
        "status": "approved",
        "kind": "preference",
        "memory_key": "different_key",
        "content": "全く異なる無関係なコンテンツ",
    }

    mems = [m1, m2, m3]
    # Grouping by key should join m1 and m2
    groups = build_maintenance_groups(mems, embedder=None)
    assert len(groups) == 2
    # m1 & m2 in one group, m3 in another
    g_sizes = sorted([len(g) for g in groups])
    assert g_sizes == [1, 2]

    # Test grouping by cosine similarity
    mock_embedder = MagicMock()
    # Embeddings of m1 and m2 are identical (sim = 1.0)
    mock_embedder.embed_query.side_effect = lambda text: [1.0, 0.0] if "英会話" in text else [0.0, 1.0]

    m1_no_key = {**m1, "memory_key": None}
    m2_no_key = {**m2, "memory_key": None}
    groups_sim = build_maintenance_groups([m1_no_key, m2_no_key, m3], embedder=mock_embedder)
    assert len(groups_sim) == 2


def test_validate_proposals():
    target_ids = ["mem_1", "mem_2", "mem_3"]

    p_valid = {
        "action": "merge",
        "main_id": "mem_1",
        "absorbed_ids": ["mem_2"],
        "reason": "重複マージ",
        "integrated_content": "日曜は英会話をする",
    }
    p_invalid_id = {
        "action": "merge",
        "main_id": "mem_1",
        "absorbed_ids": ["mem_non_existent"],
        "reason": "不正ID",
        "integrated_content": "本文",
    }
    p_overlap = {
        "action": "merge",
        "main_id": "mem_1",
        "absorbed_ids": ["mem_1"],
        "reason": "自己重複",
        "integrated_content": "本文",
    }

    assert len(validate_proposals([p_valid], target_ids)) == 1
    assert len(validate_proposals([p_invalid_id], target_ids)) == 0
    assert len(validate_proposals([p_overlap], target_ids)) == 0


@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_run_maintenance_diagnosis(mock_llm_response):
    # LLM return value simulating maintenance proposal JSON
    mock_llm_response.return_value = json.dumps([
        {
            "action": "merge",
            "main_id": "mem_1",
            "absorbed_ids": ["mem_2"],
            "reason": "毎週日曜日の英会話という点で重複しています。",
            "integrated_content": "毎週日曜日に英会話スクールで勉強する",
        }
    ])

    mems = [
        {
            "memory_id": "mem_1",
            "status": "approved",
            "kind": "preference",
            "memory_key": "pref",
            "content": "毎週日曜日に英会話をする",
        },
        {
            "memory_id": "mem_2",
            "status": "approved",
            "kind": "preference",
            "memory_key": "pref",
            "content": "日曜は英会話に行く",
        },
    ]

    base_date = datetime(2026, 7, 25, tzinfo=timezone(timedelta(hours=9)))
    proposals = run_maintenance_diagnosis(base_date, mems)
    assert len(proposals) == 1
    assert proposals[0]["action"] == "merge"
    assert proposals[0]["main_id"] == "mem_1"
    assert proposals[0]["absorbed_ids"] == ["mem_2"]


def test_apply_single_proposal():
    conn = get_db_connection()
    try:
        # Seed test db memories
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM memory_events")

        m1 = {
            "schema_version": 1,
            "memory_id": "mem_1",
            "status": "approved",
            "kind": "preference",
            "content": "毎週日曜日に英会話をする",
            "topics": json.dumps(["学習"]),
            "tags": json.dumps(["英語"]),
            "evidence": json.dumps([{"path": "daily/2026-07-20.md", "observed_at": "2026-07-20"}]),
        }
        m2 = {
            "schema_version": 1,
            "memory_id": "mem_2",
            "status": "approved",
            "kind": "preference",
            "content": "日曜は英会話スクールに行く",
            "topics": json.dumps(["その他"]),
            "tags": json.dumps(["趣味"]),
            "evidence": json.dumps([{"path": "daily/2026-07-21.md", "observed_at": "2026-07-21"}]),
        }

        for m in (m1, m2):
            conn.execute(
                "INSERT INTO memories (schema_version, memory_id, status, kind, content, topics, tags, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (m["schema_version"], m["memory_id"], m["status"], m["kind"], m["content"], m["topics"], m["tags"], m["evidence"])
            )
        conn.commit()

        # Build memories map
        memories_map = {
            "mem_1": {
                "memory_id": "mem_1",
                "status": "approved",
                "kind": "preference",
                "content": "毎週日曜日に英会話をする",
                "topics": ["学習"],
                "tags": ["英語"],
                "evidence": [{"path": "daily/2026-07-20.md", "observed_at": "2026-07-20"}],
            },
            "mem_2": {
                "memory_id": "mem_2",
                "status": "approved",
                "kind": "preference",
                "content": "日曜は英会話スクールに行く",
                "topics": ["その他"],
                "tags": ["趣味"],
                "evidence": [{"path": "daily/2026-07-21.md", "observed_at": "2026-07-21"}],
            },
        }

        p = {
            "action": "merge",
            "main_id": "mem_1",
            "absorbed_ids": ["mem_2"],
            "reason": "マージテスト",
            "integrated_content": "毎週日曜日に英会話スクールに行って勉強する",
        }

        with conn:
            apply_single_proposal(conn, p, "proposal_1", memories_map)

        # Verify m1 is updated with integrated content & inherited topics/tags/evidence
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE memory_id = 'mem_1'")
        row1 = dict(cursor.fetchone())
        assert row1["content"] == "毎週日曜日に英会話スクールに行って勉強する"
        assert "その他" in json.loads(row1["topics"])
        assert "趣味" in json.loads(row1["tags"])
        ev1 = json.loads(row1["evidence"])
        assert len(ev1) == 2

        # Verify m2 status is updated to superseded
        cursor.execute("SELECT * FROM memories WHERE memory_id = 'mem_2'")
        row2 = dict(cursor.fetchone())
        assert row2["status"] == "superseded"

        # Verify events exist
        cursor.execute("SELECT * FROM memory_events")
        events = cursor.fetchall()
        assert len(events) >= 2
    finally:
        conn.close()


@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_full_hitl_maintenance_lifecycle(mock_llm_response):
    conn = get_db_connection()
    try:
        # Seed test db memories
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM hitl_runs")
        conn.execute("DELETE FROM hitl_questions")

        m1 = {
            "schema_version": 1,
            "memory_id": "mem_1",
            "status": "approved",
            "kind": "preference",
            "content": "毎週日曜日に英会話をする",
            "topics": json.dumps(["学習"]),
            "tags": json.dumps(["英語"]),
            "evidence": json.dumps([{"path": "daily/2026-07-20.md", "observed_at": "2026-07-20"}]),
            "updated_at": "2026-07-20T00:00:00+09:00",
        }
        m2 = {
            "schema_version": 1,
            "memory_id": "mem_2",
            "status": "approved",
            "kind": "preference",
            "content": "日曜は英会話スクールに行く",
            "topics": json.dumps(["その他"]),
            "tags": json.dumps(["趣味"]),
            "evidence": json.dumps([{"path": "daily/2026-07-21.md", "observed_at": "2026-07-21"}]),
            "updated_at": "2026-07-21T00:00:00+09:00",
        }

        for m in (m1, m2):
            conn.execute(
                "INSERT INTO memories (schema_version, memory_id, status, kind, content, topics, tags, evidence, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (m["schema_version"], m["memory_id"], m["status"], m["kind"], m["content"], m["topics"], m["tags"], m["evidence"], m["updated_at"])
            )
        conn.commit()

        # Base Date & Map
        base_date = datetime(2026, 7, 25, tzinfo=timezone(timedelta(hours=9)))
        memories_map = {
            "mem_1": {
                "memory_id": "mem_1",
                "status": "approved",
                "kind": "preference",
                "content": "毎週日曜日に英会話をする",
                "topics": ["学習"],
                "tags": ["英語"],
                "evidence": [{"path": "daily/2026-07-20.md", "observed_at": "2026-07-20"}],
                "updated_at": "2026-07-20T00:00:00+09:00",
            },
            "mem_2": {
                "memory_id": "mem_2",
                "status": "approved",
                "kind": "preference",
                "content": "日曜は英会話スクールに行く",
                "topics": ["その他"],
                "tags": ["趣味"],
                "evidence": [{"path": "daily/2026-07-21.md", "observed_at": "2026-07-21"}],
                "updated_at": "2026-07-21T00:00:00+09:00",
            },
        }

        # 1. Register Run
        proposals = [
            {
                "action": "merge",
                "main_id": "mem_1",
                "absorbed_ids": ["mem_2"],
                "reason": "英会話の重複",
                "integrated_content": "毎週日曜日に英会話スクールに行って勉強する",
            }
        ]

        run_id = register_maintenance_hitl_run(base_date, proposals, memories_map)
        assert run_id is not None

        # 2. Verify registered details
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hitl_runs WHERE run_id = ?", (run_id,))
        run_row = cursor.fetchone()
        assert run_row is not None
        assert run_row["status"] == "pending_user"

        cursor.execute("SELECT * FROM hitl_questions WHERE run_id = ?", (run_id,))
        qs = cursor.fetchall()
        assert len(qs) == 1
        q = qs[0]
        assert q["question_key"] == "proposal_1"
        assert q["question_type"] == "select"

        # 3. User submits answer: apply
        submit_answer(run_id, "round_1", "proposal_1", "apply")

        # Register hander in registry just in case conftest missed it
        from obsidian_ai_hub.hitl.dispatcher import register_handler
        register_handler("memory.apply_maintenance_proposals", run_approved_maintenance)

        # 4. Dispatch runs
        processed = dispatch_runs(conn)
        assert processed == 1

        # 5. Verify Run completed and DB applied
        cursor.execute("SELECT * FROM hitl_runs WHERE run_id = ?", (run_id,))
        run_row = cursor.fetchone()
        assert run_row["status"] == "completed"

        cursor.execute("SELECT * FROM memories WHERE memory_id = 'mem_1'")
        row1 = dict(cursor.fetchone())
        assert row1["content"] == "毎週日曜日に英会話スクールに行って勉強する"

        cursor.execute("SELECT * FROM memories WHERE memory_id = 'mem_2'")
        row2 = dict(cursor.fetchone())
        assert row2["status"] == "superseded"

        # Check Markdown approved.md output file
        approved_md_path = get_approved_memories_path()
        assert approved_md_path.exists()
        md_content = approved_md_path.read_text(encoding="utf-8")
        assert "毎週日曜日に英会話スクールに行って勉強する" in md_content

    finally:
        conn.close()


@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_maintenance_snapshot_conflict_re_diagnose(mock_llm_response):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM hitl_runs")
        conn.execute("DELETE FROM hitl_questions")

        # Seed initial memories
        m1 = {
            "schema_version": 1,
            "memory_id": "mem_1",
            "status": "approved",
            "kind": "preference",
            "content": "毎週日曜日に英会話をする",
            "updated_at": "2026-07-20T00:00:00+09:00",
        }
        m2 = {
            "schema_version": 1,
            "memory_id": "mem_2",
            "status": "approved",
            "kind": "preference",
            "content": "日曜は英会話スクールに行く",
            "updated_at": "2026-07-21T00:00:00+09:00",
        }
        for m in (m1, m2):
            conn.execute(
                "INSERT INTO memories (schema_version, memory_id, status, kind, content, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (m["schema_version"], m["memory_id"], m["status"], m["kind"], m["content"], m["updated_at"])
            )
        conn.commit()

        base_date = datetime(2026, 7, 25, tzinfo=timezone(timedelta(hours=9)))
        memories_map = {
            "mem_1": m1,
            "mem_2": m2,
        }

        proposals = [
            {
                "action": "merge",
                "main_id": "mem_1",
                "absorbed_ids": ["mem_2"],
                "reason": "英会話の重複",
                "integrated_content": "毎週日曜日に英会話スクールに行って勉強する",
            }
        ]

        run_id = register_maintenance_hitl_run(base_date, proposals, memories_map)

        # Simulate concurrent/external modification: modify updated_at of mem_1 in the DB!
        conn.execute("UPDATE memories SET updated_at = ? WHERE memory_id = 'mem_1'", ("2026-07-25T12:00:00+09:00",))
        conn.commit()

        # User submits "apply"
        submit_answer(run_id, "round_1", "proposal_1", "apply")

        # Set up mock LLM re-diagnosis output (e.g. no_action)
        mock_llm_response.return_value = json.dumps([
            {
                "action": "no_action",
                "main_id": "mem_1",
                "absorbed_ids": [],
                "reason": "外部変更があったため、統合をキャンセルし現状維持とします。",
                "integrated_content": None,
            }
        ])

        from obsidian_ai_hub.hitl.dispatcher import register_handler
        register_handler("memory.apply_maintenance_proposals", run_approved_maintenance)

        # Dispatch
        processed = dispatch_runs(conn)
        assert processed == 1

        # Verify run completed directly with no new round because of "no_action"
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hitl_runs WHERE run_id = ?", (run_id,))
        run_row = cursor.fetchone()
        assert run_row["status"] == "completed"

    finally:
        conn.close()


@patch("obsidian_ai_hub.line_notification.notify_hitl_run")
def test_register_maintenance_hitl_run_notifies_initial_round(mock_notify):
    """Initial maintenance registration emits exactly one inbox notification via the central path."""
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM hitl_runs")
        conn.execute("DELETE FROM hitl_questions")

        m1 = {
            "schema_version": 1,
            "memory_id": "mem_1",
            "status": "approved",
            "kind": "preference",
            "content": "毎週日曜日に英会話をする",
            "updated_at": "2026-07-20T00:00:00+09:00",
        }
        m2 = {
            "schema_version": 1,
            "memory_id": "mem_2",
            "status": "approved",
            "kind": "preference",
            "content": "日曜は英会話スクールに行く",
            "updated_at": "2026-07-21T00:00:00+09:00",
        }
        for m in (m1, m2):
            conn.execute(
                "INSERT INTO memories (schema_version, memory_id, status, kind, content, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (m["schema_version"], m["memory_id"], m["status"], m["kind"], m["content"], m["updated_at"])
            )
        conn.commit()

        base_date = datetime(2026, 7, 25, tzinfo=timezone(timedelta(hours=9)))
        memories_map = {"mem_1": m1, "mem_2": m2}
        proposals = [
            {
                "action": "merge",
                "main_id": "mem_1",
                "absorbed_ids": ["mem_2"],
                "reason": "英会話の重複",
                "integrated_content": "毎週日曜日に英会話スクールに行って勉強する",
            }
        ]

        run_id = register_maintenance_hitl_run(base_date, proposals, memories_map)
        assert run_id is not None
        # Central notification (hitl.service._notify_hitl_if_needed) is the
        # sole initial notification; the explicit helper is not used here.
        mock_notify.assert_not_called()
        row = conn.execute(
            "SELECT COUNT(*) FROM notification_inbox WHERE target_id = ?;",
            (run_id,),
        ).fetchone()
        assert int(row[0]) == 1
    finally:
        conn.close()


@patch("obsidian_ai_hub.line_notification.notify_hitl_run")
@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_maintenance_reproposal_round_notifies(mock_llm_response, mock_notify):
    """The feedback-triggered next round sends one notification with its round number."""
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM hitl_runs")
        conn.execute("DELETE FROM hitl_questions")

        m1 = {
            "schema_version": 1,
            "memory_id": "mem_1",
            "status": "approved",
            "kind": "preference",
            "content": "毎週日曜日に英会話をする",
            "updated_at": "2026-07-20T00:00:00+09:00",
        }
        m2 = {
            "schema_version": 1,
            "memory_id": "mem_2",
            "status": "approved",
            "kind": "preference",
            "content": "日曜は英会話スクールに行く",
            "updated_at": "2026-07-21T00:00:00+09:00",
        }
        for m in (m1, m2):
            conn.execute(
                "INSERT INTO memories (schema_version, memory_id, status, kind, content, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (m["schema_version"], m["memory_id"], m["status"], m["kind"], m["content"], m["updated_at"])
            )
        conn.commit()

        base_date = datetime(2026, 7, 25, tzinfo=timezone(timedelta(hours=9)))
        memories_map = {"mem_1": m1, "mem_2": m2}
        proposals = [
            {
                "action": "merge",
                "main_id": "mem_1",
                "absorbed_ids": ["mem_2"],
                "reason": "英会話の重複",
                "integrated_content": "毎週日曜日に英会話スクールに行って勉強する",
            }
        ]

        run_id = register_maintenance_hitl_run(base_date, proposals, memories_map)
        assert run_id is not None
        # Initial round uses the central notification path, not the explicit
        # helper; the explicit helper fires only for the re-proposal below.
        mock_notify.assert_not_called()
        mock_notify.reset_mock()

        submit_answer(run_id, "round_1", "proposal_1", {"value": "feedback", "comment": "もっと自然な日本語に修正してください"})

        mock_llm_response.return_value = json.dumps([
            {
                "action": "merge",
                "main_id": "mem_1",
                "absorbed_ids": ["mem_2"],
                "reason": "フィードバックを反映し調整しました。",
                "integrated_content": "毎週日曜日に英会話スクールへ行く",
            }
        ])

        from obsidian_ai_hub.hitl.dispatcher import register_handler
        register_handler("memory.apply_maintenance_proposals", run_approved_maintenance)

        processed = dispatch_runs(conn)
        assert processed == 1

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hitl_runs WHERE run_id = ?", (run_id,))
        run_row = dict(cursor.fetchone())
        assert run_row["status"] == "pending_user"
        assert run_row["active_question_set_id"] == "round_2"

        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["run_id"] == run_id
        assert kwargs["round_number"] == 2
        assert "再提案" in kwargs["description"]
    finally:
        conn.close()


@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_maintenance_feedback_creates_next_round(mock_llm_response):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM hitl_runs")
        conn.execute("DELETE FROM hitl_questions")

        # Seed initial memories
        m1 = {
            "schema_version": 1,
            "memory_id": "mem_1",
            "status": "approved",
            "kind": "preference",
            "content": "毎週日曜日に英会話をする",
            "updated_at": "2026-07-20T00:00:00+09:00",
        }
        m2 = {
            "schema_version": 1,
            "memory_id": "mem_2",
            "status": "approved",
            "kind": "preference",
            "content": "日曜は英会話スクールに行く",
            "updated_at": "2026-07-21T00:00:00+09:00",
        }
        for m in (m1, m2):
            conn.execute(
                "INSERT INTO memories (schema_version, memory_id, status, kind, content, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (m["schema_version"], m["memory_id"], m["status"], m["kind"], m["content"], m["updated_at"])
            )
        conn.commit()

        base_date = datetime(2026, 7, 25, tzinfo=timezone(timedelta(hours=9)))
        memories_map = {
            "mem_1": m1,
            "mem_2": m2,
        }

        proposals = [
            {
                "action": "merge",
                "main_id": "mem_1",
                "absorbed_ids": ["mem_2"],
                "reason": "英会話の重複",
                "integrated_content": "毎週日曜日に英会話スクールに行って勉強する",
            }
        ]

        run_id = register_maintenance_hitl_run(base_date, proposals, memories_map)

        # User submits "feedback" with a comment
        # submit_answer takes (run_id, question_set_id, question_key, answer_payload)
        submit_answer(run_id, "round_1", "proposal_1", {"value": "feedback", "comment": "もっと自然な日本語に修正してください"})

        # Mock LLM feedback assessment (yields adjusted merge proposal)
        mock_llm_response.return_value = json.dumps([
            {
                "action": "merge",
                "main_id": "mem_1",
                "absorbed_ids": ["mem_2"],
                "reason": "フィードバックを反映し調整しました。",
                "integrated_content": "毎週日曜日に英会話スクールへ行く",
            }
        ])

        from obsidian_ai_hub.hitl.dispatcher import register_handler
        register_handler("memory.apply_maintenance_proposals", run_approved_maintenance)

        # Dispatch
        processed = dispatch_runs(conn)
        assert processed == 1

        # Run should now be re-suspended in "pending_user" with "round_2" active set
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hitl_runs WHERE run_id = ?", (run_id,))
        run_row = dict(cursor.fetchone())
        assert run_row["status"] == "pending_user"
        assert run_row["active_question_set_id"] == "round_2"

        # Verify there is a new question in round_2
        cursor.execute("SELECT * FROM hitl_questions WHERE run_id = ? AND question_set_id = 'round_2'", (run_id,))
        qs = cursor.fetchall()
        assert len(qs) == 1
        q = dict(qs[0])
        assert q["question_key"] == "proposal_1"
        assert "毎週日曜日に英会話スクールへ行く" in q["context_json"]

    finally:
        conn.close()


def test_register_maintenance_hitl_run_notify_failure_does_not_fail_registration(monkeypatch):
    """A raising central notification must not fail the maintenance run registration."""

    def _boom(event):
        raise RuntimeError("push down")

    monkeypatch.setattr(
        "obsidian_ai_hub.notifications.publish_notification", _boom
    )
    monkeypatch.setattr(
        "obsidian_ai_hub.notifications.publisher.publish_notification", _boom
    )
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM hitl_runs")
        conn.execute("DELETE FROM hitl_questions")

        m1 = {
            "schema_version": 1,
            "memory_id": "mem_1",
            "status": "approved",
            "kind": "preference",
            "content": "毎週日曜日に英会話をする",
            "updated_at": "2026-07-20T00:00:00+09:00",
        }
        m2 = {
            "schema_version": 1,
            "memory_id": "mem_2",
            "status": "approved",
            "kind": "preference",
            "content": "日曜は英会話スクールに行く",
            "updated_at": "2026-07-21T00:00:00+09:00",
        }
        for m in (m1, m2):
            conn.execute(
                "INSERT INTO memories (schema_version, memory_id, status, kind, content, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (m["schema_version"], m["memory_id"], m["status"], m["kind"], m["content"], m["updated_at"])
            )
        conn.commit()

        base_date = datetime(2026, 7, 25, tzinfo=timezone(timedelta(hours=9)))
        memories_map = {"mem_1": m1, "mem_2": m2}
        proposals = [
            {
                "action": "merge",
                "main_id": "mem_1",
                "absorbed_ids": ["mem_2"],
                "reason": "英会話の重複",
                "integrated_content": "毎週日曜日に英会話スクールに行って勉強する",
            }
        ]

        run_id = register_maintenance_hitl_run(base_date, proposals, memories_map)
        assert run_id is not None

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hitl_runs WHERE run_id = ?", (run_id,))
        assert cursor.fetchone() is not None
    finally:
        conn.close()


@patch("obsidian_ai_hub.line_notification.notify_hitl_run", side_effect=RuntimeError("push down"))
@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_maintenance_reproposal_notify_failure_does_not_fail_run(mock_llm_response, mock_notify):
    """A raising notification during the next-round registration must not fail the run."""
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM hitl_runs")
        conn.execute("DELETE FROM hitl_questions")

        m1 = {
            "schema_version": 1,
            "memory_id": "mem_1",
            "status": "approved",
            "kind": "preference",
            "content": "毎週日曜日に英会話をする",
            "updated_at": "2026-07-20T00:00:00+09:00",
        }
        m2 = {
            "schema_version": 1,
            "memory_id": "mem_2",
            "status": "approved",
            "kind": "preference",
            "content": "日曜は英会話スクールに行く",
            "updated_at": "2026-07-21T00:00:00+09:00",
        }
        for m in (m1, m2):
            conn.execute(
                "INSERT INTO memories (schema_version, memory_id, status, kind, content, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (m["schema_version"], m["memory_id"], m["status"], m["kind"], m["content"], m["updated_at"])
            )
        conn.commit()

        base_date = datetime(2026, 7, 25, tzinfo=timezone(timedelta(hours=9)))
        memories_map = {"mem_1": m1, "mem_2": m2}
        proposals = [
            {
                "action": "merge",
                "main_id": "mem_1",
                "absorbed_ids": ["mem_2"],
                "reason": "英会話の重複",
                "integrated_content": "毎週日曜日に英会話スクールに行って勉強する",
            }
        ]

        run_id = register_maintenance_hitl_run(base_date, proposals, memories_map)
        assert run_id is not None

        submit_answer(run_id, "round_1", "proposal_1", {"value": "feedback", "comment": "もっと自然な日本語に修正してください"})

        mock_llm_response.return_value = json.dumps([
            {
                "action": "merge",
                "main_id": "mem_1",
                "absorbed_ids": ["mem_2"],
                "reason": "フィードバックを反映し調整しました。",
                "integrated_content": "毎週日曜日に英会話スクールへ行く",
            }
        ])

        from obsidian_ai_hub.hitl.dispatcher import register_handler
        register_handler("memory.apply_maintenance_proposals", run_approved_maintenance)

        processed = dispatch_runs(conn)
        assert processed == 1

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hitl_runs WHERE run_id = ?", (run_id,))
        run_row = dict(cursor.fetchone())
        assert run_row["status"] == "pending_user"
        assert run_row["active_question_set_id"] == "round_2"
    finally:
        conn.close()


@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_reassess_candidate_memories(mock_llm_response):
    from obsidian_ai_hub.memory import save_all_memories, load_all_memories, get_memory_events
    from obsidian_ai_hub.memory.maintenance import reassess_candidate_memories
    from obsidian_ai_hub.memory.models import compute_memory_fingerprint

    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM memory_events")
        conn.commit()
    finally:
        conn.close()

    m_target = {
        "schema_version": 1,
        "memory_id": "mem_target_re",
        "status": "approved",
        "kind": "preference",
        "memory_key": "key-re",
        "content": "承認済みのターゲット記憶",
        "topics": ["学習"],
        "tags": ["英語"],
        "evidence": [],
        "created_at": "2026-07-01T00:00:00+09:00",
        "updated_at": "2026-07-01T00:00:00+09:00",
    }

    # Candidate 1: reassessment_required = True
    c1 = {
        "schema_version": 1,
        "memory_id": "mem_cand_re1",
        "status": "candidate",
        "kind": "preference",
        "memory_key": "key-re",
        "content": "再判定が必要な候補記憶1",
        "topics": ["学習"],
        "tags": ["英語"],
        "evidence": [],
        "dedup_suggestions": [{"target_memory_id": "mem_target_re", "relation": "duplicate"}],
        "dedup_assessment": {
            "decision": "merge",
            "target_memory_id": "mem_target_re",
            "reassessment_required": True,
            "reassessment_reason": "対象変更",
        },
        "created_at": "2026-07-01T00:00:00+09:00",
        "updated_at": "2026-07-01T00:00:00+09:00",
    }

    # Candidate 2: no matching approved memory exists anymore -> becomes "new"
    c2 = {
        "schema_version": 1,
        "memory_id": "mem_cand_re2",
        "status": "candidate",
        "kind": "fact",
        "memory_key": "key-orphaned",
        "content": "対象が存在しない孤立候補記憶2",
        "topics": ["その他"],
        "tags": [],
        "evidence": [],
        "dedup_suggestions": [{"target_memory_id": "mem_non_existent", "relation": "duplicate"}],
        "dedup_assessment": {
            "decision": "merge",
            "target_memory_id": "mem_non_existent",
            "reassessment_required": True,
        },
        "created_at": "2026-07-01T00:00:00+09:00",
        "updated_at": "2026-07-01T00:00:00+09:00",
    }

    save_all_memories([m_target, c1, c2])

    mock_llm_response.return_value = json.dumps([
        {
            "candidate_id": "mem_cand_re1",
            "decision": "merge",
            "target_memory_id": "mem_target_re",
            "integrated_content": "統合された新しい記憶1",
            "reason": "再判定でのマージ",
        }
    ])

    count = reassess_candidate_memories(embedder=None)
    assert count == 2

    all_mems = {m["memory_id"]: m for m in load_all_memories()}

    # Candidate 1 was re-assessed and has fingerprint + reassessment_required = False
    ass1 = all_mems["mem_cand_re1"]["dedup_assessment"]
    assert ass1["decision"] == "merge"
    assert ass1["target_fingerprint"] == compute_memory_fingerprint(m_target)
    assert ass1["reassessment_required"] is False

    # Candidate 2 has no approved target, so became "new"
    ass2 = all_mems["mem_cand_re2"]["dedup_assessment"]
    assert ass2["decision"] == "new"
    assert ass2["reassessment_required"] is False

    # Check audit events
    events1 = get_memory_events("mem_cand_re1")
    assert any(e["event_type"] == "dedup_reassessed" for e in events1)


def _reset_memory_tables():
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM memory_events")
        conn.commit()
    finally:
        conn.close()


def _make_reassess_target(mid="mem_target_rs", content="承認済みの内容", key="key-rs"):
    return {
        "schema_version": 1,
        "memory_id": mid,
        "status": "approved",
        "kind": "preference",
        "memory_key": key,
        "content": content,
        "topics": ["学習"],
        "tags": ["英語"],
        "evidence": [],
        "created_at": "2026-07-01T00:00:00+09:00",
        "updated_at": "2026-07-01T00:00:00+09:00",
    }


def _make_reassess_candidate(cid, target_id, target_fp, key="key-rs", extra_assessment=None):
    assessment = {
        "decision": "merge",
        "target_memory_id": target_id,
        "target_fingerprint": target_fp,
        "integrated_content": "統合内容",
        "reason": "テスト用判定",
    }
    if extra_assessment:
        assessment.update(extra_assessment)
    return {
        "schema_version": 1,
        "memory_id": cid,
        "status": "candidate",
        "kind": "preference",
        "memory_key": key,
        "content": "候補の内容",
        "topics": ["学習"],
        "tags": ["英語"],
        "evidence": [],
        "dedup_suggestions": [{"target_memory_id": target_id, "relation": "duplicate"}],
        "dedup_assessment": assessment,
        "created_at": "2026-07-01T00:00:00+09:00",
        "updated_at": "2026-07-01T00:00:00+09:00",
    }


@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_reassess_picks_up_candidate_with_stale_target_fingerprint(mock_llm):
    from obsidian_ai_hub.memory import save_all_memories, load_all_memories, update_memory_fields
    from obsidian_ai_hub.memory.maintenance import reassess_candidate_memories
    from obsidian_ai_hub.memory.models import compute_memory_fingerprint

    _reset_memory_tables()
    target = _make_reassess_target()
    cand = _make_reassess_candidate(
        "mem_cand_stale", "mem_target_rs", compute_memory_fingerprint(target)
    )
    save_all_memories([target, cand])

    # Edit the target after the assessment was saved (no explicit flag).
    update_memory_fields("mem_target_rs", {"content": "変更後の内容"})

    mock_llm.return_value = json.dumps([
        {
            "candidate_id": "mem_cand_stale",
            "decision": "merge",
            "target_memory_id": "mem_target_rs",
            "integrated_content": "統合された内容",
            "reason": "再判定でのマージ",
        }
    ])

    assert reassess_candidate_memories(embedder=None) == 1

    stored = {m["memory_id"]: m for m in load_all_memories()}
    ass = stored["mem_cand_stale"]["dedup_assessment"]
    assert ass["decision"] == "merge"
    assert ass["target_fingerprint"] == compute_memory_fingerprint(stored["mem_target_rs"])
    assert ass.get("reassessment_required") is False


def test_reassess_picks_up_candidate_with_deleted_target():
    from obsidian_ai_hub.memory import save_all_memories, load_all_memories
    from obsidian_ai_hub.memory.maintenance import reassess_candidate_memories
    from obsidian_ai_hub.memory.models import compute_memory_fingerprint

    _reset_memory_tables()
    target = _make_reassess_target()
    cand = _make_reassess_candidate(
        "mem_cand_del", "mem_target_rs", compute_memory_fingerprint(target)
    )
    save_all_memories([target, cand])

    conn = get_db_connection()
    try:
        with conn:
            conn.execute("DELETE FROM memories WHERE memory_id = ?", ("mem_target_rs",))
    finally:
        conn.close()

    assert reassess_candidate_memories(embedder=None) == 1

    stored = {m["memory_id"]: m for m in load_all_memories()}
    assert stored["mem_cand_del"]["status"] == "candidate"
    ass = stored["mem_cand_del"]["dedup_assessment"]
    assert ass["decision"] == "new"
    assert ass.get("reassessment_required") is False


@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_reassess_retries_legacy_failed_assessment_without_flag(mock_llm):
    from obsidian_ai_hub.memory import save_all_memories, load_all_memories
    from obsidian_ai_hub.memory.maintenance import reassess_candidate_memories

    _reset_memory_tables()
    save_all_memories([_make_reassess_target()])
    failed_cand = _make_reassess_candidate("mem_cand_failed", "mem_target_rs", None)
    failed_cand["dedup_assessment"] = {
        "decision": "failed",
        "similarity_score": 1.0,
        "reason": "過去の一時的なLLMエラー",
        "failure_kind": "request_failed",
    }
    save_all_memories([_make_reassess_target(), failed_cand])

    mock_llm.return_value = json.dumps([
        {
            "candidate_id": "mem_cand_failed",
            "decision": "merge",
            "target_memory_id": "mem_target_rs",
            "integrated_content": "統合された内容",
            "reason": "再試行でのマージ",
        }
    ])

    assert reassess_candidate_memories(embedder=None) == 1

    stored = {m["memory_id"]: m for m in load_all_memories()}
    ass = stored["mem_cand_failed"]["dedup_assessment"]
    assert ass["decision"] == "merge"
    assert ass.get("reassessment_required") is False
