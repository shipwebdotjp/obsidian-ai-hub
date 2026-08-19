import pytest

from obsidian_ai_hub.planner import cache


@pytest.fixture(autouse=True)
def _clear_planner_cache():
    """Clear the module-global planner cache before each test."""
    cache.invalidate_all()
    yield
    cache.invalidate_all()