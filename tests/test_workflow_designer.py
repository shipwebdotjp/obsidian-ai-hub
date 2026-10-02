"""Unit and integration tests for Workflow Designer (GraphBuilder, Catalog, Composer, API)."""

from __future__ import annotations

import json
from typing import Any, Optional
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.tasks import store as task_store
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


class FakeBuilderLLM(BaseChatModel):
    """Fake LLM that links generated node ids into an edge before finalizing.

    Reads node ids from prior ToolMessage results (like a model following
    tool results would) so the composed graph is fully connected.
    """

    turn: int = 0

    def _tool_result(self, name: str, args: dict[str, Any], call_id: str) -> ChatResult:
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="", tool_calls=[{"name": name, "args": args, "id": call_id}]
                    )
                )
            ]
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.turn += 1
        if self.turn == 1:
            return self._tool_result(
                "graph_set_metadata",
                {"name": "AI Draft Workflow", "description": "Auto generated"},
                "tc_1",
            )
        if self.turn == 2:
            return self._tool_result(
                "graph_add_node",
                {
                    "node_type": "capability",
                    "label": "Read File",
                    "node_config": {
                        "capability_key": "vault_read_file",
                        "inputs": {"relative_path": "notes/daily.md"},
                    },
                },
                "tc_2",
            )
        if self.turn == 3:
            return self._tool_result(
                "graph_add_node",
                {"node_type": "terminal", "label": "Finish", "node_config": {"outcome": "success"}},
                "tc_3",
            )
        if self.turn == 4:
            node_ids: list[str] = []
            for m in messages:
                if not isinstance(m, ToolMessage):
                    continue
                try:
                    payload = json.loads(m.content)
                except (ValueError, TypeError):
                    continue
                if isinstance(payload, dict) and payload.get("ok") and payload.get("node_id"):
                    node_ids.append(str(payload["node_id"]))
            assert len(node_ids) == 2
            return self._tool_result(
                "graph_add_edge",
                {"source_node_id": node_ids[0], "target_node_id": node_ids[1]},
                "tc_4",
            )
        if self.turn == 5:
            return self._tool_result(
                "graph_finalize",
                {"summary": "Generated draft workflow", "assumptions": ["Vault is available"]},
                "tc_5",
            )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    def bind_tools(self, tools_list: Any, **kwargs: Any) -> Any:
        return self

    @property
    def _llm_type(self) -> str:
        return "fake_builder"


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


def test_catalog_includes_workflow_only_capabilities():
    """Workflow-only capabilities (e.g. hitl_wait) are discoverable and enabled."""
    hits = catalog.catalog_search("hitl", target="capability")
    assert any(
        c["capability_key"] == "hitl_wait" and c["enabled"] is True for c in hits
    )
    det = catalog.catalog_get_details(target="capability", item_id="hitl_wait")
    assert det["ok"] is True
    assert det["enabled"] is True
    assert det["ui_target_schema"] is None
    assert isinstance(det["ui_input_schema"], dict)


def test_graph_builder_all_node_types_and_strict_auto_set():
    """Verify GraphBuilder builds all node types and auto-sets strict capability flags."""
    task_store.sync_capabilities()
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
        "max_tokens": 1024,
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
    term_res = gb.add_node("terminal", "Complete", {"outcome": "success"})
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
    assert fin["structural_errors"] == []
    assert fin["validation_issues"] == []
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


def _mixed_source_builder(key="specialist_agent"):
    """GraphBuilder with one mixed source node; returns (gb, source_id)."""
    gb = builder.GraphBuilder("Mixed", "")
    target = {"agent_id": "agent_1"} if key == "specialist_agent" else None
    inputs = (
        {"task": "analyze"}
        if key == "specialist_agent"
        else {"theme": "mixed theme"}
    )
    config = {"capability_key": key, "inputs": inputs}
    if target is not None:
        config["target"] = target
    res = gb.add_node("capability", "Source", config)
    assert res["ok"]
    return gb, res["node_id"]


def test_builder_binds_mixed_narrative_to_payload_field():
    """Narrative binds into declared payload fields without strict flags."""
    gb, source_id = _mixed_source_builder()
    write_res = gb.add_node(
        "capability",
        "Write",
        {"capability_key": "vault_write_file", "inputs": {"relative_path": "o.md"}},
    )
    assert write_res["ok"]

    bound = gb.bind_field(
        write_res["node_id"],
        "inputs.content",
        {"$ref": f"nodes.{source_id}.output.narrative.text"},
    )
    assert bound["ok"]
    source = next(n for n in gb.nodes if n["node_id"] == source_id)
    assert source["config"].get("fail_on_output_mismatch") is not True


def test_builder_rejects_mixed_narrative_to_forbidden_fields():
    """Narrative never binds into paths, commands, or delegate targets."""
    gb, source_id = _mixed_source_builder()
    write_res = gb.add_node(
        "capability",
        "Write",
        {"capability_key": "vault_write_file", "inputs": {"content": "b"}},
    )
    assert write_res["ok"]
    bad_path = gb.bind_field(
        write_res["node_id"],
        "inputs.relative_path",
        {"$ref": f"nodes.{source_id}.output.narrative.text"},
    )
    assert not bad_path["ok"]
    assert bad_path["code"] == "invalid_strict_reference"

    shell_res = gb.add_node(
        "capability", "Shell", {"capability_key": "run_shell", "inputs": {}}
    )
    assert shell_res["ok"]
    bad_command = gb.bind_field(
        shell_res["node_id"],
        "inputs.command",
        {"$ref": f"nodes.{source_id}.output.narrative.text"},
    )
    assert not bad_command["ok"]
    assert bad_command["code"] == "invalid_strict_reference"

    spec_res = gb.add_node(
        "capability",
        "Delegate",
        {
            "capability_key": "specialist_agent",
            "target": {"agent_id": "agent_1"},
            "inputs": {"task": "x"},
        },
    )
    assert spec_res["ok"]
    bad_target = gb.bind_field(
        spec_res["node_id"],
        "target.agent_id",
        {"$ref": f"nodes.{source_id}.output.narrative.text"},
    )
    assert not bad_target["ok"]
    assert bad_target["code"] == "invalid_strict_reference"


def test_builder_rejects_mixed_narrative_to_agent_inputs():
    """Agent Node inputs stay structured-only in the designer too."""
    gb, source_id = _mixed_source_builder()
    ag_res = gb.add_node(
        "agent",
        "Helper",
        {
            "agent_id": "agent_1",
            "inputs": {},
            "output_schema": {"type": "object", "properties": {}},
        },
    )
    assert ag_res["ok"]
    bad = gb.bind_field(
        ag_res["node_id"],
        "inputs.context",
        {"$ref": f"nodes.{source_id}.output.narrative.text"},
    )
    assert not bad["ok"]
    assert bad["code"] == "invalid_strict_reference"


def test_builder_llm_dict_form_contract():
    """Designer honors editor dict-form input_flow_contracts entries."""
    gb, source_id = _mixed_source_builder()
    llm_res = gb.add_node(
        "llm",
        "Summarize",
        {
            "provider": "openai",
            "model": "gpt-test",
            "system_prompt": "Summarize.",
            "max_tokens": 1024,
            "inputs": {},
            "output_schema": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
            "input_flow_contracts": {
                "report": {"accepted_value_kinds": ["structured", "narrative"]}
            },
        },
    )
    assert llm_res["ok"]
    good = gb.bind_field(
        llm_res["node_id"],
        "inputs.report",
        {"$ref": f"nodes.{source_id}.output.narrative.text"},
    )
    assert good["ok"]

    plain_res = gb.add_node(
        "llm",
        "Plain",
        {
            "provider": "openai",
            "model": "gpt-test",
            "system_prompt": "Summarize.",
            "max_tokens": 1024,
            "inputs": {},
            "output_schema": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    )
    assert plain_res["ok"]
    bad = gb.bind_field(
        plain_res["node_id"],
        "inputs.report",
        {"$ref": f"nodes.{source_id}.output.narrative.text"},
    )
    assert not bad["ok"]
    assert bad["code"] == "invalid_strict_reference"


def test_builder_mixed_receipt_condition_binding():
    """Condition-usable receipt fields bind into edge conditions only."""
    gb, source_id = _mixed_source_builder("research_agent")
    ok_res = gb.add_node("terminal", "Ok", {"outcome": "success"})
    ng_res = gb.add_node("terminal", "Ng", {"outcome": "failure"})
    assert ok_res["ok"] and ng_res["ok"]

    good = gb.add_edge(
        source_id,
        ng_res["node_id"],
        condition={
            "from_path": f"nodes.{source_id}.output.receipt.is_published",
            "operator": "equals",
            "value": True,
        },
    )
    assert good["ok"]

    bad_narrative = gb.add_edge(
        source_id,
        ok_res["node_id"],
        condition={
            "from_path": f"nodes.{source_id}.output.narrative.text",
            "operator": "exists",
        },
    )
    assert not bad_narrative["ok"]
    assert bad_narrative["code"] == "invalid_strict_reference"

    bad_id = gb.add_edge(
        source_id,
        ok_res["node_id"],
        condition={
            "from_path": f"nodes.{source_id}.output.receipt.job_id",
            "operator": "exists",
        },
    )
    assert not bad_id["ok"]
    assert bad_id["code"] == "invalid_strict_reference"


def test_builder_mixed_text_template_binding():
    """Text Template inputs accept narrative but never receipt."""
    gb, source_id = _mixed_source_builder()
    tmpl_res = gb.add_node(
        "text_template",
        "Compose",
        {"inputs": {}, "template": "{{ report }}"},
    )
    assert tmpl_res["ok"]

    good = gb.bind_field(
        tmpl_res["node_id"],
        "inputs.report",
        {"$ref": f"nodes.{source_id}.output.narrative.text"},
    )
    assert good["ok"]

    bad = gb.bind_field(
        tmpl_res["node_id"],
        "inputs.report",
        {"$ref": f"nodes.{source_id}.output.receipt.status"},
    )
    assert not bad["ok"]
    assert bad["code"] == "invalid_strict_reference"


def test_catalog_mixed_field_contracts():
    """Designer catalog exposes field contracts for mixed keys only."""
    task_store.sync_capabilities()
    for key in ("coding_cli", "specialist_agent", "research_agent"):
        det = catalog.catalog_get_details(target="capability", item_id=key)
        assert det["ok"] is True
        assert det["output_contract_class"] == "mixed"
        contracts = det["output_field_contracts"]
        assert contracts["narrative.text"]["value_kind"] == "narrative"
        assert contracts["narrative.text"]["allowed_uses"] == ["payload"]
    det = catalog.catalog_get_details(
        target="capability", item_id="vault_write_file"
    )
    assert det["ok"] is True
    assert det["output_field_contracts"] is None


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
    task_store.sync_capabilities()

    fake_llm = FakeBuilderLLM()

    # Directly test compose_workflow_draft
    compose_res = composer.compose_workflow_draft(
        "Read vault file and complete",
        custom_llm=fake_llm,
    )

    assert compose_res["package"] is not None
    assert compose_res["structural_errors"] == []
    assert compose_res["validation_issues"] == []
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


def test_builder_validate_flags_disabled_capability_and_unknown_agent():
    """Builder validation reports disabled capabilities and missing agents."""
    task_store.sync_capabilities()
    task_store.update_capability("vault_read_file", enabled=False)
    try:
        gb = builder.GraphBuilder("Invalid refs", "")
        cap = gb.add_node(
            "capability", "Read", {"capability_key": "vault_read_file", "inputs": {}}
        )
        assert cap["ok"]
        ag = gb.add_node(
            "agent",
            "Helper",
            {
                "agent_id": "agent_does_not_exist",
                "inputs": {},
                "output_schema": {"type": "object"},
            },
        )
        assert ag["ok"]
        res = gb.validate()
        assert res["structural_errors"] == []
        messages = " ".join(i["message"] for i in res["validation_issues"])
        assert "vault_read_file" in messages and "無効" in messages
        assert "agent_does_not_exist" in messages
    finally:
        task_store.update_capability("vault_read_file", enabled=True)


def test_composer_requires_explicit_finalize():
    """compose returns no package when the LLM never calls graph_finalize."""
    seq = [
        [{
            "name": "graph_set_metadata",
            "args": {"name": "No Finalize", "description": ""},
            "id": "tc_1",
        }],
        [{
            "name": "graph_add_node",
            "args": {"node_type": "terminal", "label": "End", "node_config": {"outcome": "success"}},
            "id": "tc_2",
        }],
    ]
    fake_llm = FakeToolSequenceLLM(tool_sequence=seq)
    res = composer.compose_workflow_draft("Build without finalize", custom_llm=fake_llm)
    assert res["package"] is None
    assert res["structural_errors"] != []
    assert res["structural_errors"][0]["code"] == "finalize_not_called"


def test_composer_surfaces_rejected_finalize_errors(monkeypatch):
    """When the built graph has structural errors, the real errors are returned."""
    seq = [
        [{
            "name": "graph_add_node",
            "args": {"node_type": "terminal", "label": "End", "node_config": {"outcome": "success"}},
            "id": "tc_1",
        }],
    ]
    fake_llm = FakeToolSequenceLLM(tool_sequence=seq)

    def _broken_validate(self):
        return {
            "ok": False,
            "structural_errors": [{"code": "structural_error", "message": "boom"}],
            "validation_issues": [],
        }

    monkeypatch.setattr(builder.GraphBuilder, "validate", _broken_validate)
    res = composer.compose_workflow_draft("Broken graph", custom_llm=fake_llm)
    assert res["package"] is None
    assert res["structural_errors"] == [{"code": "structural_error", "message": "boom"}]


def test_composer_logs_tool_results():
    """Tool args and results are persisted to llm_call_logs per turn."""
    seq = [
        [{
            "name": "graph_set_metadata",
            "args": {"name": "Logged", "description": ""},
            "id": "tc_1",
        }],
        [{
            "name": "graph_add_node",
            "args": {"node_type": "terminal", "label": "End", "node_config": {"outcome": "success"}},
            "id": "tc_2",
        }],
        [{
            "name": "graph_finalize",
            "args": {"summary": "s", "assumptions": []},
            "id": "tc_3",
        }],
    ]
    fake_llm = FakeToolSequenceLLM(tool_sequence=seq)
    res = composer.compose_workflow_draft("Log check", custom_llm=fake_llm)
    assert res["package"] is not None

    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT tool_calls_json FROM llm_call_logs WHERE call_id LIKE 'wfd_%' "
            "ORDER BY started_at DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()
    assert rows
    found_finalize_result = False
    for row in rows:
        for tc in json.loads(row["tool_calls_json"]):
            if tc.get("tool_name") == "graph_finalize":
                assert tc.get("status") == "succeeded"
                assert isinstance(tc.get("result"), str)
                assert '"ok": true' in tc.get("result")
                found_finalize_result = True
    assert found_finalize_result


def test_graph_builder_loop_subgraph():
    """Builder constructs a valid loop child graph with condition and loop_result."""
    task_store.sync_capabilities()
    gb = builder.GraphBuilder("Loop Test", "")

    loop = gb.add_node("loop", "Repeat", {})
    assert loop["ok"]
    lid = loop["node_id"]

    child = gb.add_node(
        "llm",
        "Step",
        {
            "provider": "openai",
            "model": "gpt-5.4",
            "system_prompt": "s",
            "max_tokens": 128,
            "inputs": {},
            "output_schema": {
                "type": "object",
                "properties": {"done": {"type": "boolean"}},
                "required": ["done"],
            },
        },
        parent_loop_node_id=lid,
    )
    assert child["ok"]
    cid = child["node_id"]

    lres = gb.add_node("loop_result", "Collect", {}, parent_loop_node_id=lid)
    assert lres["ok"]
    out_map = gb.set_node_config(str(lres["node_id"]), {"output_mapping": {}})
    assert out_map["ok"]

    cfg = gb.configure_loop(
        loop_node_id=lid,
        entry_node_id=cid,
        state_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        },
        continuation_condition={
            "from_path": "loop.state.count",
            "operator": "equals",
            "value": 3,
        },
        max_iterations=5,
        input_mapping={"count": 0},
    )
    assert cfg["ok"], cfg

    e1 = gb.add_edge(cid, str(lres["node_id"]))
    assert e1["ok"]
    term = gb.add_node("terminal", "Done", {"outcome": "success"})
    assert term["ok"]
    e2 = gb.add_edge(lid, str(term["node_id"]))
    assert e2["ok"]

    fin = gb.finalize("loop summary", [])
    assert fin["ok"], fin
    assert fin["structural_errors"] == []
    assert fin["validation_issues"] == [], fin["validation_issues"]
