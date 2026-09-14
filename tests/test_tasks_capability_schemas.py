"""Tests for the single-source capability schema layer."""

import pytest

from obsidian_ai_hub.agents.registry import MemoryProposeInput
from obsidian_ai_hub.tasks import capability_schemas as schemas
from obsidian_ai_hub.tasks.capabilities import CAPABILITY_DEFINITIONS


def test_all_capabilities_resolve_input_model():
    missing = [
        d.key for d in CAPABILITY_DEFINITIONS if schemas.resolve_input_model(d.key) is None
    ]
    assert missing == []


def test_memory_propose_required_is_content_kind():
    model = schemas.resolve_input_model("memory_propose")
    assert model is MemoryProposeInput
    assert set(model.model_json_schema().get("required", [])) == {"content", "kind"}


def test_compact_schema_reflects_constraints():
    text = schemas.compact_schema_text("memory_propose")
    assert text is not None
    assert "content" in text and "required" in text
    assert "preference" in text  # kind enum/Literal surfaces
    assert "unknown keys forbidden" in text  # extra="forbid" policy

    search_text = schemas.compact_schema_text("memory_search")
    assert search_text is not None
    assert "query" in search_text
    assert "minimum" in search_text or "maximum" in search_text  # limit range

    key_text = schemas.compact_schema_text("memory_propose")
    assert "pattern" in key_text  # memory_key pattern surfaces


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


def test_no_circular_import():
    import sys

    for module in ("obsidian_ai_hub.tasks.capability_schemas",):
        sys.modules.pop(module, None)
    import importlib

    module = importlib.import_module("obsidian_ai_hub.tasks.capability_schemas")
    assert module.resolve_input_model("web_search") is not None


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
        schemas.validate_capability_inputs("run_shell", {"command": "ls"})
