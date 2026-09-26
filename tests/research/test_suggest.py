from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from obsidian_ai_hub import suggest_research_theme
from obsidian_ai_hub.research import feedback
from obsidian_ai_hub.tasks import store as task_store


def test_suggest_research_theme_submits_task(test_memory_db_path):
    receipt = suggest_research_theme.main(host="127.0.0.1", port=8765)
    assert isinstance(receipt, dict)
    assert "task_id" in receipt
    assert receipt["status"] == "queued"
    assert receipt["detail_url"] == f"http://127.0.0.1:8765/task-agent/{receipt['task_id']}"

    task = task_store.get_task(receipt["task_id"])
    assert task is not None
    assert task["status"] == "queued"
    assert suggest_research_theme.SUGGEST_RESEARCH_THEME_PROMPT in task["prompt_text"]


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

        with patch("obsidian_ai_hub.research.runner.run_research", return_value=mock_report):
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


def test_suggestion_hitl_run_approve_with_comment_and_execute(tmp_path: Path, monkeypatch, test_memory_db_path):
    """Test approving a suggested research theme HITL Run with a comment, which runs research, forwards comment to context, and saves to vault."""
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub import hitl
    from obsidian_ai_hub.research import db as research_db
    from obsidian_ai_hub.main import register_hitl_handlers

    register_hitl_handlers()

    conn = get_db_connection()
    try:
        theme_rec = research_db.create_theme(
            theme="コメント付き自動承認テーマ",
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

        # Submit answer with a comment in {"value": "approve", "comment": "This is a comment"} format
        hitl.submit_answer(
            run_id,
            "confirm_suggest",
            "action",
            {"value": "approve", "comment": "This is my special approval comment."},
            conn,
        )

        # Dispatch HITL Runs with mock research report
        from obsidian_ai_hub.research.runner import ResearchReport
        mock_report = ResearchReport(
            title="コメント付き自動承認テーマの調査結果",
            mode="internal",
            markdown="---\ntitle: コメント付き自動承認テーマの調査結果\nstatus: researched\n---\n## 調査結果詳細",
        )

        with patch("obsidian_ai_hub.research.runner.run_research", return_value=mock_report) as mock_conduct:
            processed = hitl.dispatch_runs(conn)
            assert processed == 1

            # Assert that run_research was called and passed our comment in context parameter!
            mock_conduct.assert_called_once()
            assert mock_conduct.call_args.kwargs.get("context") == "This is my special approval comment."

        # Check theme is approved and job succeeded
        theme_obj = research_db.get_theme(theme_id, conn=conn)
        assert theme_obj["status"] == "approved"
        assert theme_obj["feedback_decision"] == "approved"
        assert theme_obj["feedback_reason"] is None
        assert theme_obj["feedback_comment"] == "This is my special approval comment."
        assert theme_obj["feedback_at"] is not None

    finally:
        conn.close()


def test_suggestion_approve_comment_stays_out_of_router_and_title(
    tmp_path: Path, monkeypatch, test_memory_db_path
):
    """HITL approval comment reaches the final prompt but not router/title.

    New input boundary: router sees theme/direction/why_now only, the title
    is generated from the theme only, and the job still publishes exactly once
    with the generated title.
    """
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub import hitl
    from obsidian_ai_hub.research import db as research_db, runner
    from obsidian_ai_hub.main import register_hitl_handlers

    register_hitl_handlers()

    conn = get_db_connection()
    try:
        theme_rec = research_db.create_theme(
            theme="境界分離テーマ",
            direction="方向",
            kind="explore",
            why_now="理由",
            confidence=0.8,
            status="candidate",
            conn=conn,
        )
        theme_id = theme_rec["theme_id"]
        run_id = f"hrun_suggest_{theme_id}"
        _register_suggestion_run(conn, theme_id, run_id)
        hitl.submit_answer(
            run_id,
            "confirm_suggest",
            "action",
            {"value": "approve", "comment": "approval-comment-sensitive"},
            conn,
        )

        captured_router: dict = {}
        captured_title: dict = {}
        captured_prompt: dict = {}
        real_collect = runner.collect_research_context
        real_build = runner.build_research_prompt

        def fake_router(theme, *, why_now=None, direction=None):
            captured_router["theme"] = theme
            captured_router["why_now"] = why_now
            captured_router["direction"] = direction
            return runner.ResearchRouteDecision(mode=runner.RESEARCH_MODE_INTERNAL)

        def fake_collect(theme, explicit_context=None):
            result = real_collect(theme, explicit_context)
            captured_prompt["collected"] = result
            return result

        def fake_title(theme):
            captured_title["theme"] = theme
            return "境界タイトル"

        def fake_build(theme, *, mode, context=None, **kwargs):
            captured_prompt["final_context"] = context
            return real_build(
                theme, mode=mode, context=context, **kwargs
            )

        monkeypatch.setattr(runner, "route_research_topic", fake_router)
        monkeypatch.setattr(runner, "collect_research_context", fake_collect)
        monkeypatch.setattr(runner, "generate_research_title", fake_title)
        monkeypatch.setattr(runner, "build_research_prompt", fake_build)
        monkeypatch.setattr(
            runner, "conduct_research", lambda *a, **kw: "境界本文"
        )

        processed = hitl.dispatch_runs(conn)
        assert processed == 1

        assert captured_router == {
            "theme": "境界分離テーマ",
            "why_now": "理由",
            "direction": "方向",
        }
        assert "approval-comment-sensitive" not in str(captured_router.values())
        assert captured_title == {"theme": "境界分離テーマ"}
        assert "approval-comment-sensitive" in captured_prompt["collected"]
        assert (
            captured_prompt["final_context"] == captured_prompt["collected"]
        )
        assert "approval-comment-sensitive" in captured_prompt["final_context"]

        job = research_db.latest_job(theme_id, conn=conn)
        assert job["status"] == "succeeded"
        assert job["generated_title"] == "境界タイトル"
        assert job["is_published"] == 1
        output = Path(job["output_path"])
        assert output.exists()
        assert "境界タイトル" in output.name
        assert job["job_id"] in output.name
        assert len(list(output.parent.glob(f"*{job['job_id']}*.md"))) == 1
    finally:
        conn.close()


def _register_suggestion_run(conn, theme_id: str, run_id: str) -> None:
    from obsidian_ai_hub import hitl

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


def test_suggestion_approve_auto_project_routes_and_saves(
    tmp_path: Path, monkeypatch, test_memory_db_path
):
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub import hitl
    from obsidian_ai_hub.research import db as research_db, runner
    from obsidian_ai_hub.main import register_hitl_handlers

    register_hitl_handlers()

    conn = get_db_connection()
    try:
        theme_rec = research_db.create_theme(
            theme="承認PJルーティング",
            direction="Obsidian AI Hub の実装",
            kind="explore",
            why_now="理由",
            confidence=0.8,
            status="candidate",
            conn=conn,
        )
        theme_id = theme_rec["theme_id"]
        run_id = f"hrun_suggest_{theme_id}"
        _register_suggestion_run(conn, theme_id, run_id)
        hitl.submit_answer(run_id, "confirm_suggest", "action", "approve", conn)

        monkeypatch.setattr(runner, "collect_research_context", lambda theme, ctx=None: "")
        monkeypatch.setattr(
            runner,
            "route_research_topic",
            lambda *a, **k: runner.ResearchRouteDecision(
                mode=runner.RESEARCH_MODE_PROJECT, project_id=7, confidence=0.9
            ),
        )
        monkeypatch.setattr(runner, "_resolve_project_label", lambda pid: "Obsidian AI Hub")
        monkeypatch.setattr(runner, "generate_research_title", lambda theme: "title")

        captured: dict = {}

        def fake_conduct(prompt, *, mode, output_style=None, project_id=None):
            captured["project_id"] = project_id
            captured["persisted_project_id"] = research_db.get_theme(theme_id)[
                "project_id"
            ]
            return "report body"

        monkeypatch.setattr(runner, "conduct_research", fake_conduct)

        processed = hitl.dispatch_runs(conn)
        assert processed == 1

        theme_obj = research_db.get_theme(theme_id, conn=conn)
        assert theme_obj["status"] == "approved"
        assert theme_obj["project_id"] == 7
        # The project is persisted before the coding agent is started.
        assert captured["persisted_project_id"] == 7

        job = research_db.latest_job(theme_id, conn=conn)
        assert job["status"] == "succeeded"
        assert job["project_id"] == 7
        assert job["is_published"] == 1
        assert captured["project_id"] == 7
        assert Path(job["output_path"]).exists()
    finally:
        conn.close()


def test_suggestion_approve_project_coding_failure_skips_vault(
    tmp_path: Path, monkeypatch, test_memory_db_path
):
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub import hitl
    from obsidian_ai_hub.research import db as research_db, runner
    from obsidian_ai_hub.research.coding_research import CodingResearchError
    from obsidian_ai_hub.main import register_hitl_handlers

    register_hitl_handlers()

    conn = get_db_connection()
    try:
        theme_rec = research_db.create_theme(
            theme="承認PJ失敗",
            direction="方向",
            kind="explore",
            why_now="理由",
            confidence=0.8,
            status="candidate",
            conn=conn,
        )
        theme_id = theme_rec["theme_id"]
        run_id = f"hrun_suggest_{theme_id}"
        _register_suggestion_run(conn, theme_id, run_id)
        hitl.submit_answer(run_id, "confirm_suggest", "action", "approve", conn)

        monkeypatch.setattr(runner, "collect_research_context", lambda theme, ctx=None: "")
        monkeypatch.setattr(
            runner,
            "route_research_topic",
            lambda *a, **k: runner.ResearchRouteDecision(
                mode=runner.RESEARCH_MODE_PROJECT, project_id=7, confidence=0.9
            ),
        )
        monkeypatch.setattr(runner, "_resolve_project_label", lambda pid: "Obsidian AI Hub")
        monkeypatch.setattr(runner, "generate_research_title", lambda theme: "title")

        def boom(*args, **kwargs):
            raise CodingResearchError("agent boom")

        monkeypatch.setattr(runner, "conduct_research", boom)

        processed = hitl.dispatch_runs(conn)
        assert processed == 1

        theme_obj = research_db.get_theme(theme_id, conn=conn)
        assert theme_obj["status"] == "approved"
        assert theme_obj["project_id"] == 7

        job = research_db.latest_job(theme_id, conn=conn)
        assert job["status"] == "failed"
        assert job["project_id"] == 7
        assert job["output_path"] is None
        assert job["is_published"] == 0
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


REJECT_REASON_VALUES = sorted(feedback.ALLOWED_FEEDBACK_REASONS)


@pytest.mark.parametrize("reason", REJECT_REASON_VALUES)
def test_suggestion_hitl_run_reject_with_reason_saves_feedback(
    tmp_path: Path, monkeypatch, test_memory_db_path, reason: str
):
    """Rejecting with each of the 6 reason choices saves status + feedback and skips research."""
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub import hitl
    from obsidian_ai_hub.research import db as research_db
    from obsidian_ai_hub.main import register_hitl_handlers

    register_hitl_handlers()

    conn = get_db_connection()
    try:
        theme_rec = research_db.create_theme(
            theme=f"テスト却下理由_{reason}",
            direction="方向",
            kind="explore",
            why_now="理由",
            confidence=0.8,
            status="candidate",
            conn=conn,
        )
        theme_id = theme_rec["theme_id"]
        run_id = f"hrun_reject_{reason}_{theme_id}"

        questions_data = [
            {
                "question_key": "action",
                "question_type": "select",
                "display_text": "Approve?",
                "choices": ["approve", *(c["value"] for c in feedback.FEEDBACK_ACTION_CHOICES)],
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
        hitl.submit_answer(
            run_id,
            "confirm_suggest",
            "action",
            {"value": f"reject:{reason}", "comment": "補足メモ"},
            conn,
        )

        processed = hitl.dispatch_runs(conn)
        assert processed == 1

        theme_obj = research_db.get_theme(theme_id, conn=conn)
        assert theme_obj["status"] == "rejected"
        assert theme_obj["feedback_decision"] == "rejected"
        assert theme_obj["feedback_reason"] == reason
        assert theme_obj["feedback_comment"] == "補足メモ"
        assert theme_obj["feedback_at"] is not None

        job = research_db.latest_job(theme_id, conn=conn)
        assert job is None
    finally:
        conn.close()
