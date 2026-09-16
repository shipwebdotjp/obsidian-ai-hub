"""Unit tests for coding worker usage accumulation across attempts."""

from __future__ import annotations

from obsidian_ai_hub.coding import usage


def test_accumulate_sums_additive_and_maxes_context_counters():
    totals = usage.new_usage_totals()
    usage.accumulate_usage(
        totals,
        {"input": 100, "output": 20, "total": 150, "cached": 30, "used": 1200, "size": 200000},
    )
    usage.accumulate_usage(
        totals,
        {"input": 50, "output": 5, "total": 60, "cached": 10, "used": 2000, "size": 200000},
    )

    assert totals["input"] == 150
    assert totals["output"] == 25
    assert totals["total"] == 210
    assert totals["cached"] == 40
    # Context-window counters are snapshots, never summed.
    assert totals["used_max"] == 2000
    assert totals["size_max"] == 200000


def test_accumulate_ignores_none_and_negative_values():
    totals = usage.new_usage_totals()
    usage.accumulate_usage(totals, None)
    usage.accumulate_usage(totals, {"input": -5, "output": True, "total": "x"})

    assert totals["input"] == 0
    assert totals["output"] == 0
    assert totals["total"] == 0


def test_accumulate_sums_cost_and_keeps_last_currency():
    totals = usage.new_usage_totals()
    usage.accumulate_usage(totals, {"cost": {"amount": 0.01, "currency": "USD"}})
    usage.accumulate_usage(totals, {"cost": {"amount": 0.02, "currency": "JPY"}})

    assert totals["cost"]["amount"] == 0.03
    assert totals["cost"]["currency"] == "JPY"


def test_attach_writes_block_and_attempt_count_when_usage_present():
    totals = usage.new_usage_totals()
    usage.accumulate_usage(totals, {"input": 10, "output": 2, "total": 12, "cached": 0})
    diag: dict = {"transport": "acp"}

    usage.attach_usage_cumulative(diag, totals, attempt_count=3)

    assert diag["usage_cumulative"]["input"] == 10
    assert diag["usage_cumulative"]["output"] == 2
    assert diag["usage_cumulative"]["total"] == 12
    assert diag["worker_attempt_count"] == 3


def test_attach_omits_zero_context_and_cost_values():
    totals = usage.new_usage_totals()
    usage.accumulate_usage(totals, {"input": 10, "output": 2, "total": 12})
    diag: dict = {"transport": "acp"}

    usage.attach_usage_cumulative(diag, totals, attempt_count=1)

    block = diag["usage_cumulative"]
    assert "used_max" not in block
    assert "size_max" not in block
    assert "cost" not in block


def test_attach_keeps_reported_context_and_cost_values():
    totals = usage.new_usage_totals()
    usage.accumulate_usage(
        totals,
        {"input": 10, "used": 500, "size": 200000, "cost": {"amount": 0.02, "currency": "USD"}},
    )
    diag: dict = {"transport": "acp"}

    usage.attach_usage_cumulative(diag, totals, attempt_count=1)

    block = diag["usage_cumulative"]
    assert block["used_max"] == 500
    assert block["size_max"] == 200000
    assert block["cost"] == {"amount": 0.02, "currency": "USD"}


def test_attach_keeps_cost_only_attempts():
    totals = usage.new_usage_totals()
    usage.accumulate_usage(totals, {"cost": {"amount": 0.05, "currency": "USD"}})
    diag: dict = {"transport": "acp"}

    usage.attach_usage_cumulative(diag, totals, attempt_count=1)

    assert diag["usage_cumulative"]["cost"] == {"amount": 0.05, "currency": "USD"}
    assert diag["worker_attempt_count"] == 1


def test_attach_skips_empty_totals():
    diag: dict = {"transport": "acp"}
    usage.attach_usage_cumulative(diag, usage.new_usage_totals(), attempt_count=0)

    assert "usage_cumulative" not in diag
    assert "worker_attempt_count" not in diag


def test_restore_from_cumulative_block():
    prior = {
        "usage_cumulative": {
            "input": 150,
            "output": 25,
            "total": 210,
            "cached": 40,
            "used_max": 2000,
            "size_max": 200000,
            "cost": {"amount": 0.03, "currency": "USD"},
        },
        "worker_attempt_count": 2,
    }

    totals = usage.usage_totals_from_diagnostics(prior)

    assert totals["input"] == 150
    assert totals["used_max"] == 2000
    assert totals["cost"]["amount"] == 0.03
    usage.accumulate_usage(totals, {"input": 5, "output": 1, "total": 6})
    assert totals["input"] == 155
    assert totals["total"] == 216


def test_restore_falls_back_to_legacy_last_attempt_usage():
    totals = usage.usage_totals_from_diagnostics(
        {"usage": {"input": 100, "output": 20, "total": 120, "used": 900, "size": 200000}}
    )

    assert totals["input"] == 100
    assert totals["total"] == 120
    assert totals["used_max"] == 900
    assert totals["size_max"] == 200000


def test_restore_handles_missing_diagnostics():
    totals = usage.usage_totals_from_diagnostics(None)

    assert totals == usage.new_usage_totals()
