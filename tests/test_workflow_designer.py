"""Unit and integration tests for Workflow Designer (GraphBuilder, Catalog, Composer, API)."""

from __future__ import annotations

import json
from typing import Any, Optional
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils import config
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.workflow.designer import builder, catalog, composer, tools
from obsidian_ai_hub.workflow import store as workflow_store


# --- Fake LLM Helper ---


class FakeToolSequenceLLM(BaseChatModel):
    tool_sequence: list[list[dict[str, Any]]]
    turn: int = 0

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.turn < len(self.tool_sequence):
            tc_list = self.tool_sequence[self.turn]
            self.turn += 1
            if tc_list:
                return ChatResult(
                    generations=[
                        ChatGeneration(
                            message=AIMessage(content="", tool_calls=tc_list)
                        )
                    ]
                )
        self.turn += 1
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="Finalized"))]
        )

    def bind_tools(self, tools_list: Any, **kwargs: Any) -> Any:
        return self

    @property
    def _llm_type(self) -> str:
        return "fake_tool_sequence"


# --- Unit Tests ---


def test_catalog_search_privacy_and_limits():
    """Verify catalog search respects privacy bounds and 10-item limits."""
    # Capabilities
    caps = catalog.catalog_search("", target="capability")
    assert len(caps) <= 10
    assert all("capability_key" in c and "label" in c for c in caps)

    # Agents
    agents = catalog.catalog_search("", target="agent")
    assert len(agents) <= 10
    for ag in agents:
        assert "system_prompt" not in ag
        assert "system_prompt_template" not in ag

    # Projects
    projects = catalog.catalog_search("", target="project")
    assert len(projects) <= 10
    for p in projects:
        assert "working_path" not in p
        assert "details" not in p

    # People
    people = catalog.catalog_search("", target="person")
    assert len(people) <= 10
    for p in people:
        assert "properties" not in p
        assert "notes" not in p

    # Vault
    vault_files = catalog.catalog_search("", target="vault")
    assert len(vault_files) <= 10
    for vf in vault_files:
        assert "content" not in vf


def test_graph_builder_all_node_types_and_strict_auto_set():
    """Verify GraphBuilder builds all node types and auto-sets strict capability flags."""
    gb = builder.GraphBuilder("Test Graph", "Description")
    gb.set_inputs_schema({
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
    })

    # Add Capability Node (vault_read_file - structured, strict_allowed)
    cap_res = gb.add_node("capability", "Read Note", {"capability_key": "vault_read_file", "inputs": {}})
    assert cap_res["ok"]
    c_node_id = cap_res["node_id"]

    # Bind input referencing run.inputs
    bind_res1 = gb.bind_field(c_node_id, "inputs.relative_path", {"$ref": "run.inputs.file_path"})
    assert bind_res1["ok"]

    # Add LLM Node
    llm_res = gb.add_node("llm", "Extract Key Topics", {
        "provider": "openai",
        "model": "gpt-5.4",
        "system_prompt": "Extract topic",
        "inputs": {},
        "output_schema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
        },
    })
    assert llm_res["ok"]
    llm_node_id = llm_res["node_id"]

    # Bind LLM input referencing vault_read_file output
    # This MUST auto-set fail_on_output_mismatch = True on the vault_read_file node!
    bind_res2 = gb.bind_field(
        llm_node_id,
        "inputs.text",
        {"$ref": f"nodes.{c_node_id}.output.content"},
    )
    assert bind_res2["ok"]

    # Verify fail_on_output_mismatch is now True on c_node_id
    cap_node = next(n for n in gb.nodes if n["node_id"] == c_node_id)
    assert cap_node["config"].get("fail_on_output_mismatch") is True

    # Add Terminal Node
    term_res = gb.add_node("terminal", "Complete", {"outcome": "completed"})
    assert term_res["ok"]
    term_node_id = term_res["node_id"]

    # Add Edges
    e1 = gb.add_edge(c_node_id, llm_node_id)
    assert e1["ok"]
    e2 = gb.add_edge(llm_node_id, term_node_id)
    assert e2["ok"]

    # Finalize
    fin = gb.finalize("Full test graph summary", ["Assumption A"])
    assert fin["ok"]
    assert fin["package"] is not None
    assert len(fin["package"]["nodes"]) == 3
    assert len(fin["package"]["edges"]) == 2
    # Verify deterministic layout ui_position is assigned
    assert all(n["ui_position"] is not None for n in fin["package"]["nodes"])


def test_strict_capability_reference_errors():
    """Verify recoverable tool errors when referencing non-strict or receipt/opaque capabilities."""
    gb = builder.GraphBuilder("Strict Test", "")

    # Add web_search (opaque output, strict NOT allowed)
    ws_res = gb.add_node("capability", "Web Search", {"capability_key": "web_search"})
    ws_node_id = ws_res["node_id"]

    # Add LLM node
    llm_res = gb.add_node("llm", "LLM Node", {
        "output_schema": {"type": "object", "properties": {"res": {"type": "string"}}},
    })
    llm_node_id = llm_res["node_id"]

    # Attempting to bind reference to web_search output MUST fail with recoverable error
    bind_res = gb.bind_field(
        llm_node_id,
        "inputs.query",
        {"$ref": f"nodes.{ws_node_id}.output.summary"},
    )
    assert not bind_res["ok"]
    assert bind_res["code"] == "invalid_strict_reference"


def test_composer_turn_budget_exceeded():
    """Verify composer raises TurnBudgetExceededError when max_turns is reached."""
    # Endless tool call sequence
    seq = [[{"name": "catalog_search", "args": {"query": "test"}, "id": f"tc_{i}"}] for i in range(40)]
    fake_llm = FakeToolSequenceLLM(tool_sequence=seq)

    with pytest.raises(composer.TurnBudgetExceededError):
        composer.compose_workflow_draft("Build a workflow", custom_llm=fake_llm)


# --- Integration API Tests ---


def test_api_unconfigured_workflow_designer(monkeypatch):
    """Verify 503 workflow_designer_not_configured when settings are missing."""
    monkeypatch.setattr(config, "LLM_WORKFLOW_DESIGNER_PROVIDER", None)
    monkeypatch.setattr(config, "LLM_WORKFLOW_DESIGNER_MODEL", None)

    app = create_app(token="test-token")
    client = TestClient(app)

    res = client.post(
        "/api/v1/workflows/designer/compose",
        json={"requirement": "Create a daily summary workflow"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert res.status_code == 503
    body = res.json()
    assert body["detail"]["code"] == "workflow_designer_not_configured"


def test_compose_and_import_end_to_end(monkeypatch):
    """End-to-end test composing a draft and importing it via POST /workflows/import."""
    monkeypatch.setattr(config, "LLM_WORKFLOW_DESIGNER_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_WORKFLOW_DESIGNER_MODEL", "gpt-5.4")

    # Sequence that creates a valid package
    seq = [
        [{
            "name": "graph_set_metadata",
            "args": {"name": "AI Draft Workflow", "description": "Auto generated"},
            "id": "tc_1",
        }],
        [{
            "name": "graph_add_node",
            "args": {"node_type": "capability", "label": "Read File", "config": {"capability_key": "vault_read_file"}},
            "id": "tc_2",
        }],
        [{
            "name": "graph_add_node",
            "args": {"node_type": "terminal", "label": "Finish", "config": {"outcome": "completed"}},
            "id": "tc_3",
        }],
        [{
            "name": "graph_finalize",
            "args": {"summary": "Generated draft workflow", "assumptions": ["Vault is available"]},
            "id": "tc_4",
        }],
    ]

    fake_llm = FakeToolSequenceLLM(tool_sequence=seq)

    # Directly test compose_workflow_draft
    compose_res = composer.compose_workflow_draft(
        "Read vault file and complete",
        custom_llm=fake_llm,
    )

    assert compose_res["package"] is not None
    assert compose_res["summary"] == "Generated draft workflow"
    assert compose_res["assumptions"] == ["Vault is available"]
    assert len(compose_res["node_analysis"]) == 2

    # Now test importing this package via Web API
    app = create_app(token="test-token")
    client_app = TestClient(app)

    import_res = client_app.post(
        "/api/v1/workflows/import",
        json=compose_res["package"],
        headers={"Authorization": "Bearer test-token"},
    )

    assert import_res.status_code == 201
    import_body = import_res.json()
    assert "workflow" in import_body
    assert "revision" in import_body
    revision = import_body["revision"]
    assert revision["status"] == "draft"

    # Verify workflow in DB keeps skip_approval = false
    wf_id = import_body["workflow"]["workflow_id"]
    wf_detail = workflow_store.get_workflow(wf_id)
    assert wf_detail is not None
    assert wf_detail.get("skip_approval") == 0 or wf_detail.get("skip_approval") is False
