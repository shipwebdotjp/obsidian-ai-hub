from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub.research import suggest as suggest_research_theme


from obsidian_ai_hub.activity.store import add_activity


def _write_activity_log(
    base_dir: Path, activity_date: date, summaries: list[str]
) -> Path:
    for i, s in enumerate(summaries):
        add_activity(
            activity_date=activity_date.strftime("%Y-%m-%d"),
            occurred_at=f"{activity_date.strftime('%Y-%m-%d')}T12:{i:02d}:00",
            summary=s,
            category="開発",
            keywords=["test"],
        )
    return base_dir / f"{activity_date.strftime('%Y-%m-%d')}.jsonl"


def test_build_suggestions_uses_activity_context_and_avoids_existing(
    tmp_path: Path,
    monkeypatch,
    test_memory_db_path: Path,
):
    today = date.today()
    activity_root = tmp_path / "activity"

    _write_activity_log(
        activity_root,
        today,
        [
            "Obsidian の見出し設計を考える",
            "タスク管理の切り口を検討",
        ],
    )
    _write_activity_log(
        activity_root,
        today - timedelta(days=1),
        [
            "ノート構造の見直し",
        ],
    )

    monkeypatch.setattr(suggest_research_theme.config, "ACTIVITY_PATH", activity_root)

    from obsidian_ai_hub.research import db as research_themes

    assert suggest_research_theme.config.MEMORY_SQLITE_PATH == test_memory_db_path
    research_themes.create_theme(
        theme="既存テーマA", direction="既存の方向", kind="deep", confidence=0.9
    )
    rejected = research_themes.create_theme(
        theme="却下済みテーマ", direction="却下方向", kind="explore", confidence=0.5
    )
    research_themes.set_status(rejected["theme_id"], "rejected")

    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "deep",
                    "theme": "意思決定ログの設計",
                    "direction": "判断の前提と保留条件を残す方法を整理する",
                    "why_now": "最近のノートで判断の迷いが繰り返し出ているため",
                    "confidence": 0.95,
                },
                {
                    "kind": "adjacent",
                    "theme": "ノート構造と検索導線の接点",
                    "direction": "見出しとタグの設計が再検索性にどう効くかを調べる",
                    "why_now": "見出し設計の話題が直近で増えているため",
                    "confidence": 0.84,
                },
                {
                    "kind": "explore",
                    "theme": "調査メモの再利用パターン",
                    "direction": "読書メモを研究テーマに変換する方法を整理する",
                    "why_now": "読書メモの扱い方を見直す必要があるため",
                    "confidence": 0.76,
                },
                {
                    "kind": "deep",
                    "theme": "既存テーマA",
                    "direction": "既存の候補と同じ内容",
                    "why_now": "重複チェック用",
                    "confidence": 0.99,
                },
            ]
        },
        ensure_ascii=False,
    )

    def fake_llm_response(
        *, provider: str, model: str, prompt: str, temperature: float, max_tokens: int
    ) -> str:
        assert "Obsidian の見出し設計" in prompt
        assert "既存テーマA" in prompt
        assert "[candidate]" in prompt
        assert "[rejected]" in prompt
        return llm_response

    with patch.object(
        suggest_research_theme.llm_client,
        "generate_llm_response",
        side_effect=fake_llm_response,
    ):
        suggestions = suggest_research_theme.build_suggestions()

    assert [item.kind for item in suggestions] == ["deep", "adjacent", "explore"]
    existing_keys = {
        suggest_research_theme._candidate_key(t.theme)
        for t in suggest_research_theme._load_existing_db_themes()
    }
    for item in suggestions:
        assert suggest_research_theme._candidate_key(item.theme) not in existing_keys
    assert len(suggestions) == 3


def test_build_suggestions_returns_empty_when_llm_output_is_invalid(
    tmp_path: Path, monkeypatch
):
    today = date.today()
    activity_root = tmp_path / "activity"
    _write_activity_log(activity_root, today, ["テストアクティビティ"])
    monkeypatch.setattr(suggest_research_theme.config, "ACTIVITY_PATH", activity_root)

    with patch.object(
        suggest_research_theme.llm_client,
        "generate_llm_response",
        side_effect=RuntimeError("boom"),
    ):
        suggestions = suggest_research_theme.build_suggestions()

    assert suggestions == []


def test_main_creates_themes_and_researches(tmp_path: Path, monkeypatch, test_memory_db_path):
    today = date.today()
    activity_root = tmp_path / "activity"
    _write_activity_log(activity_root, today, ["テストアクティビティ"])
    monkeypatch.setattr(suggest_research_theme.config, "ACTIVITY_PATH", activity_root)

    llm_response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "deep",
                    "theme": "生成テーマA",
                    "direction": "方向A",
                    "why_now": "理由A",
                    "confidence": 0.9,
                },
            ]
        },
        ensure_ascii=False,
    )

    with (
        patch.object(
            suggest_research_theme.llm_client,
            "generate_llm_response",
            return_value=llm_response,
        ),
        patch("obsidian_ai_hub.research.runner.run_theme_research") as mock_research,
    ):
        results = suggest_research_theme.main()

    assert len(results) == 1
    assert results[0]["status"] == "candidate"
    assert "hitl_run_id" in results[0]
    mock_research.assert_not_called()

    # Verify that the HITL Run is registered in DB
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub.hitl import get_run, get_questions_by_set

    conn = get_db_connection()
    try:
        run_id = results[0]["hitl_run_id"]
        run = get_run(run_id, conn)
        assert run is not None
        assert run["handler"] == "research.run_approved_suggestion"
        assert run["status"] == "pending_user"
        assert run["checkpoint"] == results[0]["theme_id"]

        questions = get_questions_by_set(run_id, "confirm_suggest", conn)
        assert len(questions) == 1
        assert questions[0]["question_key"] == "action"
        assert questions[0]["choices"] == ["approve", "reject"]
    finally:
        conn.close()


def test_suggestion_hitl_run_approve_and_execute(tmp_path: Path, monkeypatch, test_memory_db_path):
    """Test approving a suggested research theme HITL Run, which runs research, saves to vault, and approves the theme."""
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub import hitl
    from obsidian_ai_hub.research import db as research_db
    from obsidian_ai_hub.main import register_hitl_handlers

    register_hitl_handlers()

    # Step 1: Create a mock theme and register a HITL run manually
    conn = get_db_connection()
    try:
        theme_rec = research_db.create_theme(
            theme="テスト自動承認テーマ",
            direction="方向",
            kind="explore",
            why_now="理由",
            confidence=0.8,
            status="candidate",
            conn=conn,
        )
        theme_id = theme_rec["theme_id"]
        run_id = f"hrun_suggest_{theme_id}"

        questions_data = [
            {
                "question_key": "action",
                "question_type": "select",
                "display_text": "Approve?",
                "choices": ["approve", "reject"],
                "is_required": 1,
            }
        ]
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="research.run_approved_suggestion",
            checkpoint=theme_id,
            question_set_id="confirm_suggest",
            questions_data=questions_data,
            conn=conn,
        )

        # Step 2: Answer the HITL Run as 'approve'
        hitl.submit_answer(run_id, "confirm_suggest", "action", "approve", conn)

        # Step 3: Dispatch HITL Runs with mock research report
        from obsidian_ai_hub.research.runner import ResearchReport
        mock_report = ResearchReport(
            title="テスト自動承認テーマの調査結果",
            mode="internal",
            markdown="---\ntitle: テスト自動承認テーマの調査結果\nstatus: researched\n---\n## 調査結果詳細",
        )

        with patch("obsidian_ai_hub.research.runner.run_research", return_value=mock_report) as mock_conduct:
            processed = hitl.dispatch_runs(conn)
            assert processed == 1

        # Check theme is approved and job succeeded
        theme_obj = research_db.get_theme(theme_id, conn=conn)
        assert theme_obj["status"] == "approved"

        job = research_db.latest_job(theme_id, conn=conn)
        assert job["status"] == "succeeded"
        assert job["output_path"] is not None
        assert job["is_published"] == 1

        # Verify output exists
        output_file = Path(job["output_path"])
        assert output_file.exists()
        assert "## 調査結果詳細" in output_file.read_text()

    finally:
        conn.close()


def test_suggestion_hitl_run_reject(tmp_path: Path, monkeypatch, test_memory_db_path):
    """Test rejecting a suggested research theme HITL Run, which sets theme to rejected and completes without job."""
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub import hitl
    from obsidian_ai_hub.research import db as research_db
    from obsidian_ai_hub.main import register_hitl_handlers

    register_hitl_handlers()

    conn = get_db_connection()
    try:
        theme_rec = research_db.create_theme(
            theme="テスト自動却下テーマ",
            direction="方向",
            kind="explore",
            why_now="理由",
            confidence=0.8,
            status="candidate",
            conn=conn,
        )
        theme_id = theme_rec["theme_id"]
        run_id = f"hrun_suggest_{theme_id}"

        questions_data = [
            {
                "question_key": "action",
                "question_type": "select",
                "display_text": "Approve?",
                "choices": ["approve", "reject"],
                "is_required": 1,
            }
        ]
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="research.run_approved_suggestion",
            checkpoint=theme_id,
            question_set_id="confirm_suggest",
            questions_data=questions_data,
            conn=conn,
        )

        # Answer as 'reject'
        hitl.submit_answer(run_id, "confirm_suggest", "action", "reject", conn)

        # Dispatch
        processed = hitl.dispatch_runs(conn)
        assert processed == 1

        # Verify theme status is rejected and no job is created
        theme_obj = research_db.get_theme(theme_id, conn=conn)
        assert theme_obj["status"] == "rejected"

        job = research_db.latest_job(theme_id, conn=conn)
        assert job is None

    finally:
        conn.close()


def test_suggestion_hitl_run_approve_then_redispatch_idempotent(tmp_path: Path, monkeypatch, test_memory_db_path):
    """Re-dispatching an already-completed HITL run must not create a duplicate vault file or flip is_published."""
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub import hitl
    from obsidian_ai_hub.research import db as research_db
    from obsidian_ai_hub.main import register_hitl_handlers

    register_hitl_handlers()

    conn = get_db_connection()
    try:
        theme_rec = research_db.create_theme(
            theme="テスト再dispatchテーマ",
            direction="方向",
            kind="explore",
            why_now="理由",
            confidence=0.8,
            status="candidate",
            conn=conn,
        )
        theme_id = theme_rec["theme_id"]
        run_id = f"hrun_redispatch_{theme_id}"

        questions_data = [
            {
                "question_key": "action",
                "question_type": "select",
                "display_text": "Approve?",
                "choices": ["approve", "reject"],
                "is_required": 1,
            }
        ]
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="research.run_approved_suggestion",
            checkpoint=theme_id,
            question_set_id="confirm_suggest",
            questions_data=questions_data,
            conn=conn,
        )
        hitl.submit_answer(run_id, "confirm_suggest", "action", "approve", conn)

        from obsidian_ai_hub.research.runner import ResearchReport
        mock_report = ResearchReport(
            title="テスト再dispatchテーマの調査結果",
            mode="internal",
            markdown="---\ntitle: テスト再dispatchテーマの調査結果\n---\n## 調査結果",
        )
        with patch("obsidian_ai_hub.research.runner.run_research", return_value=mock_report):
            processed = hitl.dispatch_runs(conn)
            assert processed == 1

        job_after_first = research_db.latest_job(theme_id, conn=conn)
        first_output_path = job_after_first["output_path"]
        assert first_output_path is not None
        assert job_after_first["is_published"] == 1
        output_file = Path(first_output_path)
        assert output_file.exists()

        vault_file_count_before = len(list(output_file.parent.iterdir()))

        # Reset run to ready_to_resume to simulate dispatcher re-processing
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE hitl_runs
            SET status = 'ready_to_resume', lease_owner = NULL, lease_expires_at = NULL
            WHERE run_id = ?
        """, (run_id,))
        conn.commit()

        # Re-dispatch — must be idempotent
        with patch("obsidian_ai_hub.research.runner.run_research") as mock_re_run:
            processed_again = hitl.dispatch_runs(conn)

        # run_research must NOT be called when re-running a completed+published run
        mock_re_run.assert_not_called()
        assert processed_again in (0, 1)

        # Vault must have same number of files as before
        vault_file_count_after = len(list(output_file.parent.iterdir()))
        assert vault_file_count_after == vault_file_count_before

        # is_published must remain 1
        job_after_second = research_db.latest_job(theme_id, conn=conn)
        assert job_after_second["is_published"] == 1
        assert job_after_second["output_path"] == first_output_path

    finally:
        conn.close()


def test_suggestion_hitl_run_handler_failure_records_failed_status(tmp_path: Path, monkeypatch, test_memory_db_path):
    """When run_research raises inside the handler, the run transitions to failed with error details."""
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub import hitl
    from obsidian_ai_hub.research import db as research_db
    from obsidian_ai_hub.main import register_hitl_handlers

    register_hitl_handlers()

    conn = get_db_connection()
    try:
        theme_rec = research_db.create_theme(
            theme="テスト失敗恢復テーマ",
            direction="方向",
            kind="explore",
            why_now="理由",
            confidence=0.8,
            status="candidate",
            conn=conn,
        )
        theme_id = theme_rec["theme_id"]
        run_id = f"hrun_fail_{theme_id}"

        questions_data = [
            {
                "question_key": "action",
                "question_type": "select",
                "display_text": "Approve?",
                "choices": ["approve", "reject"],
                "is_required": 1,
            }
        ]
        hitl.register_run_and_questions(
            run_id=run_id,
            handler="research.run_approved_suggestion",
            checkpoint=theme_id,
            question_set_id="confirm_suggest",
            questions_data=questions_data,
            conn=conn,
        )
        hitl.submit_answer(run_id, "confirm_suggest", "action", "approve", conn)

        with patch("obsidian_ai_hub.research.runner.run_research", side_effect=RuntimeError("simulated crash")):
            processed = hitl.dispatch_runs(conn)
            assert processed == 1

        run = hitl.get_run(run_id, conn)
        assert run["status"] == "failed"
        assert "simulated crash" in (run["error_message"] or "")
        assert run["retry_count"] in (0, 1)
        assert run["lease_owner"] is None
        assert run["lease_expires_at"] is None

        theme_obj = research_db.get_theme(theme_id, conn=conn)
        assert theme_obj["status"] == "approved"

    finally:
        conn.close()
