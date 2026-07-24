import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def e2e_seed_scenario() -> list[str]:
    return ["hitl"]


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
