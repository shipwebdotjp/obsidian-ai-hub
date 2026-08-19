import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def e2e_seed_scenario() -> list[str]:
    return ["planner"]


def test_planner_shows_seeded_proposals_and_edit_saves(
    e2e_server_url: str, page: Page
) -> None:
    page.goto(f"{e2e_server_url}/planner")

    expect(page.get_by_role("heading", name="プランナー")).to_be_visible()
    expect(page.get_by_role("button", name="月", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )

    chip = page.get_by_test_id("planner-proposal-chip")
    expect(chip.filter(has_text="歯科検診")).to_be_visible()
    expect(chip.filter(has_text="図書館に本を返す")).to_be_visible()
    expect(
        page.get_by_role("button", name="✨ プロジェクトX定例レビュー")
    ).to_be_visible()

    page.get_by_role("button", name="✨ プロジェクトX定例レビュー").click()

    title = page.locator("#pp-title")
    expect(title).to_be_visible()
    title.fill("プロジェクトX定例レビュー（翌週へ）")
    page.get_by_role("button", name="保存").click()

    expect(page.get_by_text("保存しました")).to_be_visible()
    expect(
        page.get_by_role("button", name="✨ プロジェクトX定例レビュー（翌週へ）")
    ).to_be_visible()