import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def e2e_seed_scenario() -> list[str]:
    return ["summary_recovery"]


def test_generate_missing_daily_summary_from_dashboard(e2e_server_url: str, page: Page) -> None:
    """An input-only day can be recovered through the browser and persists."""
    page.goto(f"{e2e_server_url}/summary-dashboard")
    page.get_by_role("button", name="一覧").click()
    page.get_by_role("combobox").nth(1).select_option("2026-07")
    missing = page.get_by_role("button", name="日次サマリ: 2026/07/15(水)")
    expect(missing).to_be_visible()
    missing.click()
    page.get_by_role("button", name="日次サマリを作成").click()
    expect(page.get_by_role("heading", name="E2E generated recovery summary")).to_be_visible()
