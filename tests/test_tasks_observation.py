"""Tests for the two-layer Observation budgets.

The detail window is capability-specific (research reads keep more than
generic registry tools) and the history gist is a bounded, conclusion-
preserving view that is always replayed to the next Action.
"""

from obsidian_ai_hub.tasks import observation


def test_detail_limits_are_capability_specific():
    assert observation.detail_limit("research_context_snapshot") == (
        observation.MAX_DETAIL_LIMIT
    )
    assert observation.detail_limit("periodic_note_read") == (
        observation.MAX_DETAIL_LIMIT
    )
    # Generic registry tools keep the previous runtime-wide window.
    assert observation.detail_limit("vault_search") == (
        observation.DEFAULT_DETAIL_LIMIT
    )


def test_detail_truncation_uses_capability_limit():
    raw = "x" * 9000
    detail = observation.truncate_detail(raw, "research_context_snapshot")
    assert detail.startswith("x" * 100)
    assert len(detail) == observation.MAX_DETAIL_LIMIT + len("\n...(truncated)")
    assert detail.endswith("...(truncated)")

    generic = observation.truncate_detail(raw, "vault_search")
    assert len(generic) == observation.DEFAULT_DETAIL_LIMIT + len(
        "\n...(truncated)"
    )


def test_history_gist_preserves_head_and_tail_within_limit():
    head = "HEAD-" + "a" * 3000
    tail = "b" * 3000 + "-TAIL"
    gist = observation.build_history_gist(head + tail)
    assert len(gist) <= observation.HISTORY_GIST_LIMIT + 40
    assert gist.startswith("HEAD-")
    assert gist.endswith("-TAIL")
    assert "chars omitted" in gist
