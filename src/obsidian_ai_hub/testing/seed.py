"""Seed demo data for E2E tests and the exploration server.

All seed functions use the application persistence APIs (not raw SQL) so the
records have the same representation as production data.
"""

import sqlite3
from obsidian_ai_hub.testing import ensure_test_mode
from obsidian_ai_hub.testing.factories import make_memory


def seed_memory_demo_data() -> None:
    """Insert a small set of Memory Review records for browser smoke tests."""
    ensure_test_mode()

    from obsidian_ai_hub import memory as mem_mod

    candidates = [
        make_memory(
            memory_id="demo-cand-1",
            content="定例ミーティングは毎週火曜日の10時から",
            kind="fact",
            topics=["仕事"],
            tags=["会議", "定期"],
        ),
        make_memory(
            memory_id="demo-cand-2",
            content="プロジェクトXは来月までに完了させる",
            kind="commitment",
            topics=["仕事"],
            tags=["プロジェクト", "期限"],
        ),
        make_memory(
            memory_id="demo-appr-1",
            status="approved",
            content="朝のルーティン：ストレッチ→読書→日記",
            kind="pattern",
            topics=["健康"],
            tags=["習慣"],
        ),
        make_memory(
            memory_id="demo-rej-1",
            status="rejected",
            content="これは古い情報です",
            kind="fact",
            topics=["その他"],
            tags=["旧情報"],
        ),
        make_memory(
            memory_id="demo-evidence-1",
            content="Reactを採用した理由はチームの習熟度が高いため",
            kind="decision_policy",
            topics=["開発"],
            tags=["React", "技術選定"],
            evidence=[
                {
                    "path": "daily/2026-07-01.md",
                    "quote": "Reactの方が学習コストが低いという意見で一致",
                    "observed_at": "2026-07-01T12:00:00+09:00",
                }
            ],
        ),
    ]

    existing = mem_mod.load_all_memories()
    mem_mod.save_all_memories(existing + candidates)


def seed_hitl_demo_data() -> None:
    """Insert a set of HITL runs and questions directly into the temporary database."""
    ensure_test_mode()

    from obsidian_ai_hub import hitl
    from obsidian_ai_hub.research import feedback
    from obsidian_ai_hub.utils import config as app_config

    conn = sqlite3.connect(str(app_config.MEMORY_SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    try:
        # Run 1: Active suggestion pending user response (has optional notes question)
        hitl.register_run_and_questions(
            run_id="hrun_test_1",
            handler="research.run_approved_suggestion",
            checkpoint="rth_suggest_theme_1",
            question_set_id="confirm_suggest",
            questions_data=[
                {
                    "question_key": "action",
                    "question_type": "select",
                    "display_text": "「AIエージェントの未来」を調査しますか？",
                    "title": "調査の実行",
                    "prompt": "「AIエージェントの未来」を調査しますか？",
                    "choices": [
                        {"value": "approve", "label": "承認", "description": "テーマを調査し、結果をVaultに保存します。"},
                        *feedback.FEEDBACK_ACTION_CHOICES,
                    ],
                    "is_required": 1,
                    "context_json": {
                        "type": "research_suggestion",
                        "theme": "AIエージェントの未来",
                        "direction": "仕事と生活における実用的な活用方法を整理する",
                        "why_now": "最近の活動で AI エージェント活用への関心が高まっているため",
                    },
                },
                {
                    "question_key": "notes",
                    "question_type": "text",
                    "display_text": "補足メモがあれば入力してください（任意）",
                    "is_required": 0,
                }
            ],
            conn=conn,
            display_type="リサーチ提案",
            title="「AIエージェントの未来」を調査するか確認",
            description="承認すると、このテーマを詳しく調査し、結果をVaultに保存します。",
        )

        # Run 2: Another pending user run for cancellation
        hitl.register_run_and_questions(
            run_id="hrun_test_2",
            handler="dummy_handler",
            checkpoint="none",
            question_set_id="qs_cancel",
            questions_data=[
                {
                    "question_key": "confirm",
                    "question_type": "boolean",
                    "display_text": "進めますか？",
                    "choices": [True, False],
                    "is_required": 1,
                }
            ],
            conn=conn,
            display_type="進捗確認",
            title="進行確認",
            description="継続するか確認します。",
        )

        # Run 3: Optional-only questions for autoskip test
        hitl.register_run_and_questions(
            run_id="hrun_optional_only",
            handler="optional_handler",
            checkpoint="chk_opt",
            question_set_id="qs_opt",
            questions_data=[
                {
                    "question_key": "opt_a",
                    "question_type": "text",
                    "display_text": "任意のコメントA",
                    "is_required": 0,
                },
                {
                    "question_key": "opt_b",
                    "question_type": "text",
                    "display_text": "任意のコメントB",
                    "is_required": 0,
                },
            ],
            conn=conn,
            display_type="アンケート",
            title="任意のアンケート",
            description="任意の補足情報入力を求めます。",
        )

        # Pre-cancel run 2 and dispatch optional-only to test status filtering
        hitl.cancel_run("hrun_test_2", conn=conn)

        conn.commit()
    finally:
        conn.close()

    # Dispatch optional-only run so it auto-skips and completes
    conn2 = sqlite3.connect(str(app_config.MEMORY_SQLITE_PATH))
    conn2.row_factory = sqlite3.Row
    try:
        def optional_handler(ctx: hitl.HitlContext) -> hitl.HitlResult:
            return hitl.HitlResult.complete(checkpoint="done")
        hitl.register_handler("optional_handler", optional_handler)
        hitl.dispatch_runs(conn2)
    finally:
        hitl.clear_handlers()
        conn2.close()


def seed_summary_recovery_demo_data() -> None:
    """Insert one input-only day for the summary recovery E2E workflow."""
    ensure_test_mode()
    from obsidian_ai_hub.activity import store as activity_store

    activity_store.add_activity(
        activity_date="2026-07-15",
        occurred_at="2026-07-15T10:00:00",
        summary="E2E recovery input",
    )
