"""Tests for the single-source capability schema layer."""

import pytest

from obsidian_ai_hub.agents.registry import MemoryProposeInput
from obsidian_ai_hub.tasks import capability_schemas as schemas
from obsidian_ai_hub.tasks.capabilities import get_capability_definitions


def test_all_capabilities_resolve_input_model():
    missing = [
        d.key
        for d in get_capability_definitions()
        if schemas.resolve_input_model(d.key) is None
    ]
    assert missing == []


def test_memory_propose_required_is_content_kind():
    model = schemas.resolve_input_model("memory_propose")
    assert model is MemoryProposeInput
    assert set(model.model_json_schema().get("required", [])) == {"content", "kind"}


def test_runtime_injected_values_not_in_schema():
    schema = schemas.resolve_json_schema("memory_propose")
    assert schema is not None
    properties = schema.get("properties", {})
    for leaked in ("trusted_ctx", "agent_id", "session_id", "run_id", "api_key"):
        assert leaked not in properties


def test_bare_tool_schema_resolves():
    # vault_search has no hand-written input model; LangChain generates
    # args_schema from the function signature.
    model = schemas.resolve_input_model("vault_search")
    assert model is not None
    assert set(model.model_json_schema().get("required", [])) == {"query"}
    validated = schemas.validate_capability_inputs(
        "vault_search", {"query": "x", "k": 3}
    )
    assert validated["query"] == "x"


def test_people_relations_walk_schema_resolves():
    model = schemas.resolve_input_model("people_relations_walk")
    assert model is not None
    assert set(model.model_json_schema().get("required", [])) == {"person_id"}
    validated = schemas.validate_capability_inputs(
        "people_relations_walk",
        {"person_id": "peo_1", "max_hops": 2, "direction": "both"},
    )
    assert validated["person_id"] == "peo_1"
    assert validated["max_hops"] == 2
    assert validated["direction"] == "both"
    assert validated["max_nodes"] == 50
    assert validated["max_edges"] == 200
    # max_hops is capped at 3 by the single-source model.
    with pytest.raises(ValueError, match="inputs invalid"):
        schemas.validate_capability_inputs(
            "people_relations_walk", {"person_id": "peo_1", "max_hops": 9}
        )


def test_unknown_keys_rejected_before_execution():
    with pytest.raises(ValueError, match="inputs invalid"):
        schemas.validate_capability_inputs(
            "memory_propose",
            {"content": "x", "kind": "fact", "source": "instruction"},
        )


def test_missing_required_rejected():
    with pytest.raises(ValueError, match="inputs invalid"):
        schemas.validate_capability_inputs("memory_propose", {"content": "x"})


def test_enum_range_pattern_violations_rejected():
    with pytest.raises(ValueError, match="inputs invalid"):
        schemas.validate_capability_inputs(
            "memory_propose", {"content": "x", "kind": "bogus"}
        )
    with pytest.raises(ValueError, match="inputs invalid"):
        schemas.validate_capability_inputs(
            "memory_search", {"query": "x", "limit": 999}
        )
    with pytest.raises(ValueError, match="inputs invalid"):
        schemas.validate_capability_inputs(
            "memory_propose",
            {"content": "x", "kind": "fact", "memory_key": "日本語"},
        )


def test_delegate_target_models():
    target = schemas.validate_capability_target(
        "specialist_agent", {"agent_id": "agent_1"}
    )
    assert target == {"agent_id": "agent_1"}
    with pytest.raises(ValueError, match="target invalid"):
        schemas.validate_capability_target("specialist_agent", {})

    coding = schemas.validate_capability_target("coding_cli", {"project_id": "7"})
    assert coding["project_id"] == 7
    with pytest.raises(ValueError, match="target invalid"):
        schemas.validate_capability_target(
            "coding_cli", {"project_id": 7, "backend": "bogus"}
        )


def test_unresolvable_capability_rejected():
    with pytest.raises(ValueError, match="no resolvable input schema"):
        schemas.validate_capability_inputs("ask_user", {})


def test_research_agent_accepts_project_mode_and_project_id():
    inputs = schemas.validate_capability_inputs(
        "research_agent",
        {"theme": "PJ調査", "mode": "project", "project_id": "3"},
    )
    assert inputs["mode"] == "project"
    assert inputs["project_id"] == 3

    with pytest.raises(ValueError, match="inputs invalid"):
        schemas.validate_capability_inputs(
            "research_agent", {"theme": "PJ", "mode": "bogus"}
        )
