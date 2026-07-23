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
        # Run 1: Active suggestion pending user response
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
        conn.commit()
    finally:
        conn.close()


def test_hitl_sidebar_link_and_navigation(e2e_server_url: str, page: Page) -> None:
    # Go to home/memories
    page.goto(e2e_server_url)
    page.wait_for_url(f"{e2e_server_url}/memories")

    # Sidebar link should exist
    sidebar_link = page.get_by_role("link", name="確認待ち")
    expect(sidebar_link).to_be_visible()

    # Click navigation to /hitl
    sidebar_link.click()
    page.wait_for_url(f"{e2e_server_url}/hitl")
    expect(page.get_by_role("heading", name="確認待ちタスク")).to_be_visible()


def test_hitl_list_and_details_rendering(e2e_server_url: str, page: Page) -> None:
    page.goto(f"{e2e_server_url}/hitl")

    # Both seeded runs should be visible in the list
    row_1 = page.locator('[data-testid="hitl-run-row"]', has_text="hrun_test_1")
    row_2 = page.locator('[data-testid="hitl-run-row"]', has_text="hrun_test_2")
    expect(row_1).to_be_visible()
    expect(row_2).to_be_visible()

    # Click first run row and check details are loaded
    row_1.click()
    expect(page.get_by_role("heading", name="hrun_test_1")).to_be_visible()
    expect(page.locator("code", has_text="research.run_approved_suggestion")).to_be_visible()

    # Check question display text and keys are rendered
    expect(page.get_by_text("自動提案されたリサーチテーマ「AIエージェントの未来」")).to_be_visible()
    expect(page.get_by_text("補足メモがあれば入力してください（任意）")).to_be_visible()


def test_submit_hitl_answer_and_flow(e2e_server_url: str, page: Page) -> None:
    page.goto(f"{e2e_server_url}/hitl")

    # Select the first run
    page.locator('[data-testid="hitl-run-row"]', has_text="hrun_test_1").click()

    # Select choices (choices are select: 'approve', 'reject')
    # Click choice button for 'approve'
    page.get_by_role("button", name="approve").click()

    # Submit the select answer first
    page.get_by_role("button", name="回答を送信").first.click()

    # Expect the question state to show answered
    expect(page.get_by_text("回答済み").first).to_be_visible()
    expect(page.get_by_text("approve").first).to_be_visible()


def test_cancel_hitl_run(e2e_server_url: str, page: Page) -> None:
    page.goto(f"{e2e_server_url}/hitl")

    # Select second run
    page.locator('[data-testid="hitl-run-row"]', has_text="hrun_test_2").click()

    # Handle dialog confirm box on cancel button click
    page.on("dialog", lambda dialog: dialog.accept())

    # Click cancel button
    page.get_by_role("button", name="実行全体をキャンセル").click()

    # Expect status to transition to Cancelled
    expect(page.locator("span", has_text="キャンセル済み").first).to_be_visible()
