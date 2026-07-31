import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def e2e_seed_scenario() -> list[str]:
    return ["hitl"]


def test_cancel_hitl_run(e2e_server_url: str, page: Page) -> None:
    page.goto(f"{e2e_server_url}/hitl")

    # Switch to all to find hrun_test_1 (status may have changed from prior tests)
    status_filter = page.get_by_label("ステータスフィルター")
    status_filter.select_option("all")

    # Select first run
    page.locator('[data-testid="hitl-run-row"]', has_text="「AIエージェントの未来」を調査するか確認").click()

    # Handle dialog confirm box on cancel button click
    page.on("dialog", lambda dialog: dialog.accept())

    # Click cancel button
    page.get_by_role("button", name="実行全体をキャンセル").click()

    # Expect status to transition to Cancelled
    expect(page.locator("span", has_text="キャンセル済み").first).to_be_visible()
