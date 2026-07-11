import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

mock_modules = [
    "dotenv",
    "yaml",
]
for module_name in mock_modules:
    sys.modules[module_name] = MagicMock()

from obsidian_ai_hub import dashboard


@pytest.fixture
def dashboard_env(tmp_path):
    vault = tmp_path / "vault"
    activity = vault / "activity"
    daily = vault / "daily"
    dashboard_dir = vault / "dashboard"
    for path in (activity, daily, dashboard_dir):
        path.mkdir(parents=True, exist_ok=True)

    with (
        patch.object(dashboard.config, "VAULT_PATH", vault),
        patch.object(dashboard.config, "ACTIVITY_PATH", activity),
        patch.object(dashboard.config, "DAILY_PATH", daily),
        patch.object(dashboard.config, "DASHBOARD_PATH", dashboard_dir),
    ):
        yield {
            "vault": vault,
            "activity": activity,
            "daily": daily,
            "dashboard": dashboard_dir,
        }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_dashboard_exports_year_payload_and_html(dashboard_env):
    activity = dashboard_env["activity"]
    daily = dashboard_env["daily"]
    output = dashboard_env["dashboard"]

    _write_jsonl(
        activity / "2026/07/2026-07.jsonl",
        [
            {
                "date": "2026-07-10",
                "summary": "Day 10 summary",
                "topics": ["AI", "Python"],
                "keywords": ["LLM", "RAG"],
                "mood": "Calm",
                "sleep": "7h",
                "source_stats": {"activity_count": 3, "llm_session_count": 1, "has_daily_note": True},
            },
            {
                "date": "2026-07-11",
                "summary": "Day 11 summary",
                "topics": ["AI"],
                "keywords": ["Obsidian"],
                "mood": "Focused",
                "sleep": "6h",
                "source_stats": {"activity_count": 5, "llm_session_count": 2, "has_daily_note": True},
            },
        ],
    )
    _write_jsonl(
        activity / "2026/2026-week.jsonl",
        [
            {
                "week_id": "2026-W28",
                "week_start_date": "2026-07-06",
                "week_end_date": "2026-07-12",
                "summary": "Weekly summary",
                "topics": ["Planning"],
                "keywords": ["Review"],
                "mood": "Stable",
                "sleep": "Good",
                "source_stats": {"daily_record_count": 2},
            }
        ],
    )
    _write_jsonl(
        activity / "2026/2026.jsonl",
        [
            {
                "month": "2026-07",
                "summary": "Monthly summary",
                "topics": ["Monthly"],
                "keywords": ["Retro"],
                "mood": "Good",
                "sleep": "Normal",
                "source_stats": {"weekly_record_count": 1},
            }
        ],
    )

    (daily / "2026/07").mkdir(parents=True, exist_ok=True)
    (daily / "2026/07/2026-07-10.md").write_text("# Daily", encoding="utf-8")
    (daily / "2026/07/2026-07-11.md").write_text("# Daily", encoding="utf-8")
    (daily / "2026/07/2026-W28.md").write_text("# Weekly", encoding="utf-8")
    (daily / "2026/07/2026-07.md").write_text("# Monthly", encoding="utf-8")

    html_path = dashboard.build_dashboard([2026])

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    year_payload = json.loads((output / "years/2026.json").read_text(encoding="utf-8"))

    assert html_path == output / "index.html"
    assert html_path.exists()
    assert manifest["available_years"] == [2026]
    assert manifest["totals"]["daily_count"] == 2
    assert year_payload["daily"][0]["date"] == "2026-07-11"
    assert year_payload["daily"][0]["note_path"] == "daily/2026/07/2026-07-11.md"
    assert year_payload["weekly"][0]["note_path"] == "daily/2026/07/2026-W28.md"
    assert year_payload["monthly"][0]["note_path"] == "daily/2026/07/2026-07.md"
    assert "window.__DASHBOARD_BOOTSTRAP__" in html_path.read_text(encoding="utf-8")


def test_build_dashboard_generates_stats_html(dashboard_env):
    output = dashboard_env["dashboard"]
    html_path = dashboard.build_dashboard([2026])
    assert html_path == output / "index.html"
    assert html_path.exists()

    stats_path = output / "stats.html"
    assert stats_path.exists()


def test_dashboard_stats_html_contains_keywords_features(dashboard_env):
    output = dashboard_env["dashboard"]
    dashboard.build_dashboard([2026])
    stats_path = output / "stats.html"
    content = stats_path.read_text(encoding="utf-8")

    assert "display-toggle-container" in content
    assert "toggle-btn" in content
    assert "keywordsSelectorContainer" in content
    assert "keywordCandidateChips" in content
    assert "updateKeywordCandidates" in content
    assert "renderKeywordsChart" in content
    assert "state.selectedKeywords" in content


def test_dashboard_keywords_logic_with_playwright(dashboard_env):
    activity = dashboard_env["activity"]
    daily = dashboard_env["daily"]
    output = dashboard_env["dashboard"]

    # Write daily records with complex scenarios:
    # - Same-day duplicate "LLM" and Zenkaku duplicate "ＬＬＭ" on 2026-07-10
    # - More than 20 unique keywords distributed across multiple days
    _write_jsonl(
        activity / "2026/07/2026-07.jsonl",
        [
            {
                "date": "2026-07-01",
                "summary": "Day 1",
                "keywords": ["AI", "ML", "DL", "NLP", "CV", "RL", "GAN", "Transformer"],
                "source_stats": {"activity_count": 1, "llm_session_count": 1, "has_daily_note": True},
            },
            {
                "date": "2026-07-02",
                "summary": "Day 2",
                "keywords": ["C", "C++", "Java", "Go", "Rust", "Ruby", "PHP", "Scala"],
                "source_stats": {"activity_count": 1, "llm_session_count": 1, "has_daily_note": True},
            },
            {
                "date": "2026-07-03",
                "summary": "Day 3",
                "keywords": ["HTML", "CSS", "JS", "React", "Vue", "Angular", "Svelte", "Node"],
                "source_stats": {"activity_count": 1, "llm_session_count": 1, "has_daily_note": True},
            },
            {
                "date": "2026-07-10",
                "summary": "Day 10",
                "topics": ["AI"],
                "keywords": ["LLM", "LLM", "ＬＬＭ"],
                "source_stats": {"activity_count": 1, "llm_session_count": 1, "has_daily_note": True},
            },
            {
                "date": "2026-07-11",
                "summary": "Day 11",
                "topics": ["AI"],
                "keywords": ["LLM", "Python", "Python", "Ｐｙｔｈｏｎ"],
                "source_stats": {"activity_count": 1, "llm_session_count": 1, "has_daily_note": True},
            },
            {
                "date": "2026-07-12",
                "summary": "Day 12",
                "topics": ["AI"],
                "keywords": ["LLM", "Python", "Django", "FastAPI", "Flask", "Keras", "PyTorch", "NumPy"],
                "source_stats": {"activity_count": 1, "llm_session_count": 1, "has_daily_note": True},
            },
        ],
    )

    dashboard.build_dashboard([2026])
    stats_path = output / "stats.html"
    assert stats_path.exists()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(stats_path.absolute().as_uri())

        # Verify that Topics toggle is active by default
        topics_btn = page.locator("button[data-type='topics']")
        assert "active" in (topics_btn.get_attribute("class") or "")

        # Click on Keywords toggle
        keywords_btn = page.locator("button[data-type='keywords']")
        keywords_btn.click()
        assert "active" in (keywords_btn.get_attribute("class") or "")

        # Check visibility of keywords selector container
        container = page.locator("#keywordsSelectorContainer")
        assert container.is_visible()

        # Check keyword candidates list
        # "LLM" should be the top keyword (appeared on 2026-07-10, 11, 12 -> 3 days)
        # "Python" should be second (appeared on 2026-07-11, 12 -> 2 days)
        # Other keywords appeared on 1 day.
        # Candidates list should be limited to 20 chips.
        chips = page.locator("#keywordCandidateChips button.chip-btn")
        count = chips.count()
        assert count == 20

        # The first candidate chip should be "LLM"
        assert chips.nth(0).inner_text() == "LLM"
        # The second candidate chip should be "Python"
        assert chips.nth(1).inner_text() == "Python"

        # Check that top 5 chips are initially selected
        selected_chips = page.locator("#keywordCandidateChips button.chip-btn.selected")
        assert selected_chips.count() == 5

        # Check that the 6th chip is disabled because limit is 5
        disabled_chips = page.locator("#keywordCandidateChips button.chip-btn.disabled")
        assert disabled_chips.count() == 15

        # Deselect one selected chip (e.g. the 1st one, "LLM")
        chips.nth(0).click()
        assert "selected" not in (chips.nth(0).get_attribute("class") or "")

        # Since we have only 4 selected now, disabled chips should become enabled
        disabled_chips_now = page.locator("#keywordCandidateChips button.chip-btn.disabled")
        assert disabled_chips_now.count() == 0

        # Toggle granularity to monthly
        month_btn = page.locator("button[data-g='month']")
        month_btn.click()
        assert "active" in (month_btn.get_attribute("class") or "")

        # Check that some SVG line paths are rendered
        paths = page.locator("#trendsSvg path")
        assert paths.count() > 0

        # Hover over one circle marker and check tooltip
        circles = page.locator("#trendsSvg circle")
        assert circles.count() > 0

        # Dispatch mousemove on the last circle to trigger tooltip
        circles.last.dispatch_event("mousemove")
        tooltip = page.locator("#tooltip")
        assert tooltip.is_visible()
        tooltip_text = tooltip.inner_text()
        assert "キーワード:" in tooltip_text
        assert "出現日数:" in tooltip_text
        assert "対象日数:" in tooltip_text
        assert "出現率:" in tooltip_text

        browser.close()
