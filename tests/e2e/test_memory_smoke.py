import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


CANDIDATE_A_TEXT = "定例ミーティングは毎週火曜日の10時から"
CANDIDATE_B_TEXT = "プロジェクトXは来月までに完了させる"
APPROVED_TEXT = "朝のルーティン：ストレッチ→読書→日記"
EVIDENCE_CANDIDATE_TEXT = "Reactを採用した理由はチームの習熟度が高いため"
EVIDENCE_QUOTE = "Reactの方が学習コストが低いという意見で一致"


def test_page_loads_and_redirects_to_memories(e2e_server_url: str, page: Page) -> None:
    page.goto(e2e_server_url)
    page.wait_for_url(f"{e2e_server_url}/memories")
    expect(page.get_by_role("heading", name="メモリ")).to_be_visible()


def test_candidate_list_shows_seeded_memories(
    e2e_server_url: str, page: Page
) -> None:
    page.goto(f"{e2e_server_url}/memories")
    row = page.locator(
        '[data-testid="memory-row"]', has_text=CANDIDATE_A_TEXT
    )
    expect(row).to_be_visible()
    rows = page.locator('[data-testid="memory-row"]')
    expect(rows).to_have_count(3)


def test_candidate_detail_panel_shows_evidence(
    e2e_server_url: str, page: Page
) -> None:
    page.goto(f"{e2e_server_url}/memories")
    row = page.locator(
        '[data-testid="memory-row"]', has_text=EVIDENCE_CANDIDATE_TEXT
    )
    row.get_by_role("button").first.click()
    quote = page.get_by_text(EVIDENCE_QUOTE)
    expect(quote).to_be_visible()


def test_approve_candidate_removes_from_list_and_shows_in_approved(
    e2e_server_url: str, page: Page
) -> None:
    page.goto(f"{e2e_server_url}/memories")

    # Approve from candidate list
    row = page.locator('[data-testid="memory-row"]', has_text=CANDIDATE_B_TEXT)
    expect(row).to_be_visible()
    row.get_by_role("button", name="承認").click()
    page.wait_for_timeout(500)
    expect(row).not_to_be_visible()

    # Switch filter to approved
    status_select = page.get_by_label("ステータスフィルター")
    status_select.select_option("approved")
    page.wait_for_timeout(500)
    expect(page.get_by_text(CANDIDATE_B_TEXT)).to_be_visible()


def test_approved_seeded_memory_appears_in_approved_filter(
    e2e_server_url: str, page: Page
) -> None:
    page.goto(f"{e2e_server_url}/memories")
    status_select = page.get_by_label("ステータスフィルター")
    status_select.select_option("approved")
    page.wait_for_timeout(500)
    expect(page.get_by_text(APPROVED_TEXT)).to_be_visible()


def test_spa_fallback_serves_memory_page(
    e2e_server_url: str, page: Page
) -> None:
    page.goto(f"{e2e_server_url}/memories")
    expect(page.get_by_role("heading", name="メモリ")).to_be_visible()
