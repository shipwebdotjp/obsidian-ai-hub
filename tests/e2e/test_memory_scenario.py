import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


CANDIDATE_B_TEXT = "プロジェクトXは来月までに完了させる"


@pytest.fixture(scope="module")
def e2e_seed_scenario() -> list[str]:
    return ["memory"]


def test_page_loads_and_redirects_to_memories(e2e_server_url: str, page: Page) -> None:
    page.goto(e2e_server_url)
    page.wait_for_url(f"{e2e_server_url}/memories")
    expect(page.get_by_role("heading", name="メモリ")).to_be_visible()


def test_approve_candidate_removes_from_list_and_shows_in_approved(
    e2e_server_url: str, page: Page
) -> None:
    page.goto(f"{e2e_server_url}/memories")

    # Approve from candidate list
    row = page.locator('[data-testid="memory-row"]', has_text=CANDIDATE_B_TEXT)
    expect(row).to_be_visible()
    row.get_by_role("button", name="承認").click()
    expect(row).not_to_be_visible()

    # Switch filter to approved
    status_select = page.get_by_label("ステータスフィルター")
    status_select.select_option("approved")
    expect(page.get_by_text(CANDIDATE_B_TEXT)).to_be_visible()


def test_spa_fallback_serves_memory_page(
    e2e_server_url: str, page: Page
) -> None:
    page.goto(f"{e2e_server_url}/memories")
    expect(page.get_by_role("heading", name="メモリ")).to_be_visible()
