"""Unit tests for the code-owned capability effect contract."""

from obsidian_ai_hub.tasks.adapters.registry_tools import _satisfied_effects
from obsidian_ai_hub.tasks.capabilities import get_required_effects


def test_required_effects_only_from_effectful_capabilities():
    assert get_required_effects(["research_context_snapshot", "memory_search"]) == ()
    assert get_required_effects(["research_theme_propose"]) == (
        "research_theme_registered",
    )
    assert get_required_effects(
        ["research_theme_propose", "research_context_snapshot"]
    ) == ("research_theme_registered",)


def test_satisfied_effects_requires_registered_ids():
    declared = ("research_theme_registered",)
    assert (
        _satisfied_effects(
            "research_theme_propose",
            '{"status": "candidate", "theme_id": "t1", "hitl_run_id": "h1"}',
            declared,
        )
        == declared
    )
    assert (
        _satisfied_effects(
            "research_theme_propose",
            '{"status": "already_proposed", "theme_id": "t1", "hitl_run_id": "h1"}',
            declared,
        )
        == declared
    )
    assert (
        _satisfied_effects(
            "research_theme_propose", '{"error": "theme must not be blank"}', declared
        )
        == ()
    )
    assert (
        _satisfied_effects("research_theme_propose", '{"theme_id": "t1"}', declared)
        == ()
    )


def test_satisfied_effects_empty_without_declared_effects():
    assert _satisfied_effects("vault_search", '{"x": 1}', ()) == ()
