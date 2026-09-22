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


def test_ui_input_schema_flattens_optional_and_enum():
    schema = schemas.ui_input_schema("memory_search")
    assert schema is not None
    assert schema["type"] == "object"
    props = schema["properties"]
    assert props["query"]["type"] == "string"
    # Optional[Literal[...]] becomes a nullable enum, not anyOf:[X, null].
    kind = props["kind"]
    assert "anyOf" not in kind
    assert kind["nullable"] is True
    assert "preference" in kind["enum"]
    assert props["limit"]["type"] == "integer"
    assert props["limit"]["minimum"] == 1
    assert schema["required"] == ["query"]


def test_ui_input_schema_field_widget_hints():
    vault = schemas.ui_input_schema("vault_write_file")
    assert vault["properties"]["relative_path"]["x-ui"] == "vault_path"

    research = schemas.ui_input_schema("research_agent")
    assert research["properties"]["project_id"]["x-ui"] == "project"

    calendar = schemas.ui_input_schema("calendar_read")
    assert calendar["properties"]["start_date"]["x-ui"] == "date"
    assert calendar["properties"]["end_date"]["x-ui"] == "date"

    one_shot = schemas.ui_input_schema("register_one_shot_job")
    assert one_shot["properties"]["run_at"]["x-ui"] == "datetime"

    people = schemas.ui_input_schema("people_get")
    assert people["properties"]["person_id"]["x-ui"] == "person"

    specialist = schemas.ui_target_schema("specialist_agent")
    assert specialist["properties"]["agent_id"]["x-ui"] == "agent"
    coding = schemas.ui_target_schema("coding_cli")
    assert coding["properties"]["project_id"]["x-ui"] == "project"


def test_capability_output_schema_declared_and_fallback():
    declared = schemas.capability_output_schema("calendar_read")
    assert declared is not None
    assert "events" in declared["properties"]
    assert schemas.capability_output_schema("vault_search") is None

    ui = schemas.ui_output_schema("calendar_read")
    assert "events" in ui["properties"]

    # Undeclared capabilities fall back to {summary}.
    fallback = schemas.ui_output_schema("vault_search")
    assert "summary" in fallback["properties"]

    summary_cap = schemas.ui_output_schema("research_agent")
    assert "summary" in summary_cap["properties"]


def test_ui_target_schema_for_delegate_capabilities():
    assert schemas.capability_has_target("specialist_agent") is True
    assert schemas.capability_has_target("coding_cli") is True
    assert schemas.capability_has_target("vault_search") is False

    agent = schemas.ui_target_schema("specialist_agent")
    assert agent is not None
    assert "agent_id" in agent["properties"]

    coding = schemas.ui_target_schema("coding_cli")
    assert coding is not None
    assert set(coding["properties"]) >= {"project_id", "backend"}

    assert schemas.ui_target_schema("vault_search") is None


def test_ui_input_schema_available_for_all_capabilities():
    missing = [
        d.key
        for d in get_capability_definitions()
        if schemas.ui_input_schema(d.key) is None
    ]
    assert missing == []


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
