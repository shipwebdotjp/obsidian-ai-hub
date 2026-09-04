import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def e2e_seed_scenario() -> list[str]:
    return ["people"]


def test_resolve_candidate_to_unlinked_person(
    e2e_server_url: str, page: Page
) -> None:
    page.goto(f"{e2e_server_url}/people")
    expect(page.get_by_role("heading", name="人物同定・管理")).to_be_visible()

    page.get_by_role("button", name="ケン").click()
    target_box = page.get_by_label("一括解決先の人物")
    target_box.click()
    target_box.fill("鈴木健")
    page.get_by_role("option", name="鈴木健 (未連携)").click()
    page.get_by_role("button", name="解決", exact=True).click()

    expect(page.get_by_text("候補「ケン」を解決しました。")).to_be_visible()
    expect(page.get_by_text("現在、未解決候補はありません。")).to_be_visible()
