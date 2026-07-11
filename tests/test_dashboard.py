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
