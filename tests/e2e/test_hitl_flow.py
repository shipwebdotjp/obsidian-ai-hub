import sqlite3
import pytest
from playwright.sync_api import Page, expect

from obsidian_ai_hub import database
from obsidian_ai_hub import hitl
from obsidian_ai_hub.utils import config as app_config

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module", autouse=True)
def seed_hitl_data(e2e_server_url):
    """Seed HITL runs and questions directly into the temporary E2E SQLite DB."""
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
                    "display_text": "自動提案されたリサーチテーマ「AIエージェントの未来」を承認して調査を実行しますか？",
                    "choices": ["approve", "reject"],
                    "is_required": 1,
                },
                {
                    "question_key": "notes",
                    "question_type": "text",
                    "display_text": "補足メモがあれば入力してください（任意）",
                    "is_required": 0,
                }
            ],
            conn=conn,
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


def test_submit_hitl_answer_and_flow(e2e_server_url: str, page: Page) -> None:
    page.goto(f"{e2e_server_url}/hitl")

    # Select the first run
    page.locator('[data-testid="hitl-run-row"]', has_text="hrun_test_1").click()

    # Select choices (choices are select: 'approve', 'reject')
    # Click choice button for 'approve'
    page.get_by_role("button", name="approve", exact=True).click()

    # Submit the select answer first
    page.get_by_role("button", name="回答を送信").first.click()

    # Expect the question state to show answered
    expect(page.get_by_text("回答済み").first).to_be_visible()
    expect(page.get_by_text("approve").first).to_be_visible()


def test_cancel_hitl_run(e2e_server_url: str, page: Page) -> None:
    page.goto(f"{e2e_server_url}/hitl")

    # Switch to all to find hrun_test_1 (status may have changed from prior tests)
    status_filter = page.get_by_label("ステータスフィルター")
    status_filter.select_option("all")

    # Select first run (it's in ready_to_resume now, still cancellable)
    page.locator('[data-testid="hitl-run-row"]', has_text="hrun_test_1").click()

    # Handle dialog confirm box on cancel button click
    page.on("dialog", lambda dialog: dialog.accept())

    # Click cancel button
    page.get_by_role("button", name="実行全体をキャンセル").click()

    # Expect status to transition to Cancelled
    expect(page.locator("span", has_text="キャンセル済み").first).to_be_visible()
