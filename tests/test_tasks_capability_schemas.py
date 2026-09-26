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

    # Opaque capabilities have no synthetic summary fallback (P1).
    assert schemas.ui_output_schema("vault_search") is None
    assert schemas.ui_output_schema("research_agent") is None
    assert schemas.ui_output_schema("people_search") is None
    assert schemas.ui_output_schema("periodic_note_read") is None

    # Receipt schemas stay for audit/display but are not referencable (P3).
    receipt_ui = schemas.ui_output_schema("calendar_create_proposal")
    assert receipt_ui is not None
    assert "hitl_run_id" in receipt_ui["properties"]


def test_output_contract_ledger_covers_all_capabilities():
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

    # Pin the explicit inventory so a ledger regression is detected (an
    # unclassified key silently falls through to opaque).
    assert schemas.STRUCTURED_CAPABILITY_KEYS == frozenset(
        {
            "vault_read_file",
            "calendar_read",
            "reminders_read",
            "research_context_snapshot",
        }
    )
    assert schemas.RECEIPT_CAPABILITY_KEYS
    assert "vault_write_file" in schemas.RECEIPT_CAPABILITY_KEYS
    assert "calendar_create_proposal" in schemas.RECEIPT_CAPABILITY_KEYS

    by_key = {d.key: d for d in get_capability_definitions()}
    for key in schemas.STRUCTURED_CAPABILITY_KEYS:
        assert key in by_key
        assert schemas.output_contract_class(key) == "structured"
        assert schemas.output_reference_policy(key) == "strict_fields"
    for key in schemas.RECEIPT_CAPABILITY_KEYS:
        if key in by_key:
            assert schemas.output_contract_class(key) == "receipt"
            assert schemas.output_reference_policy(key) == "forbidden"
    for definition in get_capability_definitions():
        contract = schemas.output_contract_class(definition.key)
        assert contract in ("structured", "receipt", "opaque")


def test_dynamic_plugin_defaults_to_opaque():
    assert schemas.output_contract_class("custom:anything") == "opaque"
    assert schemas.output_contract_class("skills") == "opaque"
    assert schemas.output_contract_class("unknown_capability") == "opaque"
    assert schemas.ui_output_schema("custom:anything") is None


def test_p2_structured_schemas_declare_required():
    vault = schemas.capability_output_schema("vault_read_file")
    assert set(vault["required"]) == {"relative_path", "content"}

    calendar = schemas.capability_output_schema("calendar_read")
    assert set(calendar["required"]) == {
        "events",
        "apple_status",
        "recurring_status",
    }
    event_items = calendar["properties"]["events"]["items"]
    assert set(event_items["required"]) == {
        "title",
        "start",
        "end",
        "all_day",
        "source",
    }

    reminders = schemas.capability_output_schema("reminders_read")
    assert set(reminders["required"]) == {
        "reminders",
        "apple_status",
        "recurring_status",
    }

    snapshot = schemas.capability_output_schema("research_context_snapshot")
    assert set(snapshot["required"]) == {
        "recent_activities",
        "existing_themes",
        "recent_feedback",
        "daily_notes",
        "latest_weekly_note",
    }


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
