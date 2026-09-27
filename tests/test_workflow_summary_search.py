import pytest
from obsidian_ai_hub.agents import registry as agent_registry
from obsidian_ai_hub.tasks import capabilities as task_capabilities
from obsidian_ai_hub.tasks import capability_schemas


def test_summary_search_registry_and_capability_metadata():
    # 1. Registry verification
    tools = agent_registry.list_available_tools()
    tool_ids = [t["tool_id"] for t in tools]
    assert "summary_search" in tool_ids

    # 2. Task capability policy & read-only verification
    assert "summary_search" in task_capabilities.AUTO_POLICY_TOOL_IDS
    assert "summary_search" in task_capabilities.READ_ONLY_TOOL_IDS

    # 3. Capability schema classification
    assert capability_schemas.output_contract_class("summary_search") == "structured"
    assert capability_schemas.output_reference_policy("summary_search") == "strict_fields"
    assert "summary_search" in capability_schemas.STRICT_ALLOWED_REGISTRY_KEYS


def test_summary_search_input_schema_validation():
    # Valid input
    valid_inputs = {"start_date": "2026-01-01", "end_date": "2026-01-31"}
    dumped = capability_schemas.validate_capability_inputs("summary_search", valid_inputs)
    assert dumped["start_date"] == "2026-01-01"
    assert dumped["granularity"] == "auto"

    # Invalid input (unknown key forbidden)
    invalid_inputs = {"start_date": "2026-01-01", "end_date": "2026-01-31", "unknown_key": 123}
    with pytest.raises(ValueError):
        capability_schemas.validate_capability_inputs("summary_search", invalid_inputs)


def test_summary_search_strict_completeness_errors():
    # Normal output (not truncated) -> no errors
    normal_output = {
        "requested_range": {"start_date": "2026-01-01", "end_date": "2026-01-05"},
        "granularity": "day",
        "entries": [
            {
                "period_type": "day",
                "period_key": "2026-01-01",
                "period_start": "2026-01-01",
                "period_end": "2026-01-01",
                "summary_id": "sum_1",
                "summary": "Summary text",
                "matched_fields": [],
                "entry_truncated": False,
            }
        ],
        "coverage": {
            "requested_days": 5,
            "source_covered_days": 5,
            "source_missing_days": 0,
            "filter_matched_days": 5,
            "filter_unmatched_days": 0,
            "returned_days": 5,
            "source_missing_ranges": [],
            "filter_unmatched_ranges": [],
            "returned_ranges": [],
            "ranges_truncated": {
                "source_missing": False,
                "filter_unmatched": False,
                "returned": True,  # ranges_truncated in coverage alone should NOT cause strict failure
            },
        },
        "truncated": False,
        "next_request": None,
    }
    errors = capability_schemas.strict_completeness_errors("summary_search", normal_output)
    assert errors == []

    # Truncated top-level output -> errors
    truncated_top = dict(normal_output)
    truncated_top["truncated"] = True
    errors_top = capability_schemas.strict_completeness_errors("summary_search", truncated_top)
    assert len(errors_top) == 1
    assert "truncated=true" in errors_top[0]

    # Entry truncated output -> errors
    truncated_entry_output = dict(normal_output)
    truncated_entry_output["entries"] = [
        {
            "period_type": "day",
            "period_key": "2026-01-01",
            "period_start": "2026-01-01",
            "period_end": "2026-01-01",
            "summary_id": "sum_1",
            "summary": "Summary text",
            "matched_fields": [],
            "entry_truncated": True,
        }
    ]
    errors_entry = capability_schemas.strict_completeness_errors("summary_search", truncated_entry_output)
    assert len(errors_entry) == 1
    assert "切詰められています" in errors_entry[0]
