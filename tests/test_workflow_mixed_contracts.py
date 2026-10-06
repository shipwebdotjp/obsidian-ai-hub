"""Receipt/narrative contracts for the mixed delegation capabilities.

``specialist_agent`` and ``research_agent`` publish an observed ``receipt``
alongside a free-text ``narrative`` (``coding_cli`` parity). Covers:

1. Field-level contracts (value_kind / allowed_uses) for both keys.
2. Publish-time validation: narrative reaches only declared payload fields
   (direct binding and via Text Template); receipt IDs stay unreferencable
   while ``receipt.status`` / ``receipt.is_published`` work in conditions.
3. Adapter outputs: receipt + narrative shapes, and missing-report
   transitions to ``needs_attention`` without retry.
4. End-to-end execution: Specialist / Research narrative -> Text Template ->
   ``vault_write_file.content`` with a real file write.
"""

from __future__ import annotations

from pathlib import Path

from obsidian_ai_hub.research import db as research_db
from obsidian_ai_hub.research import runner as research_runner
from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.adapters.agent import AgentAdapter
from obsidian_ai_hub.tasks.adapters.research import ResearchAdapter
from obsidian_ai_hub.tasks.capability_schemas import (
    ALLOWED_USES_CONDITION,
    ALLOWED_USES_NONE,
    ALLOWED_USES_PAYLOAD,
    VALUE_KIND_NARRATIVE,
    VALUE_KIND_RECEIPT,
    get_output_field_contract,
    output_contract_class,
)
from obsidian_ai_hub.web.services import vault as vault_service
from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.execution import WorkflowEngine
from obsidian_ai_hub.workflow.models import REF_KEY
from obsidian_ai_hub.workflow.runners import DefaultNodeRunner
from obsidian_ai_hub.workflow.validation import validate_graph


def _node(node_id, node_type, config, parent=None):
    node = {
        "node_id": node_id,
        "node_type": node_type,
        "config": config,
    }
    if parent is not None:
        node["parent_loop_node_id"] = parent
    return node


def _edge(edge_id, source, target, *, condition=None, order=0, kind="normal"):
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_kind": kind,
        "condition": condition,
        "order_index": order,
    }


def _ref(path: str) -> dict[str, str]:
    return {REF_KEY: path}


def _validate(nodes, edges):
    return validate_graph(
        nodes=nodes,
        edges=edges,
        inputs_schema={"type": "object", "properties": {}},
        capability_enabled=lambda k: True,
        agent_exists=lambda a: True,
    )


def _patch_vault(monkeypatch, repo_path):
    from pathlib import Path as _Path

    from obsidian_ai_hub.utils import config as app_config

    repo_path = _Path(repo_path)
    repo_path.mkdir(parents=True, exist_ok=True)
    primary_dir = repo_path.parent / (repo_path.name + "-primary")
    primary_dir.mkdir(parents=True, exist_ok=True)
    registry = app_config.validate_vault_registry(
        {
            "vaults": {
                "main": {
                    "path": str(primary_dir),
                    "display_name": "Test Personal",
                    "role": "primary",
                    "ai_access": "read",
                },
                "blog": {
                    "path": str(repo_path),
                    "display_name": "Test Blog",
                    "ai_access": "write",
                },
            }
        }
    )
    monkeypatch.setattr(app_config, "VAULT_REGISTRY", registry)
    monkeypatch.setattr(app_config, "PRIMARY_VAULT", registry.get_primary())
    monkeypatch.setattr(app_config, "PRIMARY_VAULT_PATH", primary_dir)
    monkeypatch.setattr(app_config, "VAULT_PATH", repo_path)
    monkeypatch.setattr(vault_service.config, "VAULT_PATH", repo_path)


# --- field-level contracts -----------------------------------------------


def test_mixed_output_contract_class():
    assert output_contract_class("specialist_agent") == "mixed"
    assert output_contract_class("research_agent") == "mixed"
    assert output_contract_class("coding_cli") == "mixed"


def test_specialist_agent_field_contracts():
    assert get_output_field_contract(
        "specialist_agent", "receipt.status"
    ) == {"value_kind": VALUE_KIND_RECEIPT, "allowed_uses": ALLOWED_USES_CONDITION}
    for field in ("receipt.child_run_id", "receipt.session_id", "receipt.agent_id"):
        assert get_output_field_contract("specialist_agent", field) == {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_NONE,
        }
    assert get_output_field_contract("specialist_agent", "narrative.text") == {
        "value_kind": VALUE_KIND_NARRATIVE,
        "allowed_uses": ALLOWED_USES_PAYLOAD,
    }


def test_research_agent_field_contracts():
    for field in ("receipt.status", "receipt.is_published"):
        assert get_output_field_contract("research_agent", field) == {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_CONDITION,
        }
    for field in ("receipt.job_id", "receipt.theme_id"):
        assert get_output_field_contract("research_agent", field) == {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_NONE,
        }
    assert get_output_field_contract("research_agent", "narrative.text") == {
        "value_kind": VALUE_KIND_NARRATIVE,
        "allowed_uses": ALLOWED_USES_PAYLOAD,
    }


# --- static validation ----------------------------------------------------


def _source_node(key, node_id="s1", inputs=None, target=None):
    config = {"capability_key": key, "inputs": inputs or {}}
    if target is not None:
        config["target"] = target
    return _node(node_id, "capability", config)


def test_narrative_direct_into_vault_content_allowed():
    for key in ("specialist_agent", "research_agent"):
        target = {"agent_id": "agent_1"} if key == "specialist_agent" else None
        nodes = [
            _source_node(key, inputs={"task": "x"} if key == "specialist_agent" else {"theme": "x"}, target=target),
            _node(
                "w",
                "capability",
                {
                    "capability_key": "vault_write_file",
                    "inputs": {
                        "relative_path": "out.md",
                        "content": _ref("nodes.s1.output.narrative.text"),
                    },
                },
            ),
            _node("done", "terminal", {"outcome": "success"}),
        ]
        edges = [_edge("e1", "s1", "w"), _edge("e2", "w", "done")]
        assert _validate(nodes, edges) == [], key


def test_narrative_to_forbidden_destinations_rejected():
    cases = [
        (
            "path",
            "vault_write_file",
            {"relative_path": _ref("nodes.s1.output.narrative.text"), "content": "b"},
            None,
        ),
        (
            "command",
            "run_shell",
            {"command": _ref("nodes.s1.output.narrative.text")},
            None,
        ),
        (
            "delegate-task",
            "specialist_agent",
            {"task": _ref("nodes.s1.output.narrative.text")},
            {"agent_id": "agent_1"},
        ),
        (
            "research-theme",
            "research_agent",
            {"theme": _ref("nodes.s1.output.narrative.text")},
            None,
        ),
    ]
    for label, dest_key, dest_inputs, dest_target in cases:
        nodes = [
            _source_node(
                "specialist_agent",
                inputs={"task": "x"},
                target={"agent_id": "agent_1"},
            ),
            _node(
                "bad",
                "capability",
                {
                    "capability_key": dest_key,
                    "inputs": dest_inputs,
                    **({"target": dest_target} if dest_target is not None else {}),
                },
            ),
            _node("done", "terminal", {"outcome": "success"}),
        ]
        edges = [_edge("e1", "s1", "bad"), _edge("e2", "bad", "done")]
        errors = _validate(nodes, edges)
        assert any(e.startswith("flow_contract:") for e in errors), (
            label,
            errors,
        )


def test_narrative_in_capability_target_rejected():
    """A narrative reference is not a valid delegate target ID."""
    nodes = [
        _source_node(
            "specialist_agent", inputs={"task": "x"}, target={"agent_id": "a1"}
        ),
        _node(
            "bad",
            "capability",
            {
                "capability_key": "specialist_agent",
                "target": {"agent_id": _ref("nodes.s1.output.narrative.text")},
                "inputs": {"task": "x"},
            },
        ),
        _node("done", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "s1", "bad"), _edge("e2", "bad", "done")]
    errors = _validate(nodes, edges)
    assert errors, errors
    assert any("target" in e for e in errors), errors


def test_narrative_in_condition_rejected_but_receipt_status_allowed():
    nodes = [
        _source_node(
            "specialist_agent", inputs={"task": "x"}, target={"agent_id": "a1"}
        ),
        _node("ok", "terminal", {"outcome": "success"}),
        _node("ng", "terminal", {"outcome": "failure"}),
    ]
    bad_edges = [
        _edge(
            "e1",
            "s1",
            "ng",
            condition={
                "from_path": "nodes.s1.output.narrative.text",
                "operator": "exists",
            },
        ),
        _edge("e2", "s1", "ok"),
    ]
    errors = _validate(nodes, bad_edges)
    assert any("flow_contract" in e for e in errors)

    good_edges = [
        _edge(
            "e1",
            "s1",
            "ng",
            condition={
                "from_path": "nodes.s1.output.receipt.status",
                "operator": "equals",
                "value": "completed",
            },
        ),
        _edge("e2", "s1", "ok"),
    ]
    assert _validate(nodes, good_edges) == []


def test_receipt_ids_not_referencable_but_is_published_conditions():
    nodes = [
        _source_node("research_agent", inputs={"theme": "x"}),
        _node(
            "w",
            "capability",
            {
                "capability_key": "vault_write_file",
                "inputs": {
                    "relative_path": "out.md",
                    "content": _ref("nodes.s1.output.receipt.job_id"),
                },
            },
        ),
        _node("done", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "s1", "w"), _edge("e2", "w", "done")]
    errors = _validate(nodes, edges)
    assert any(e.startswith("output_contract:") for e in errors), errors

    cond_nodes = [
        _source_node("research_agent", inputs={"theme": "x"}),
        _node("ok", "terminal", {"outcome": "success"}),
        _node("ng", "terminal", {"outcome": "failure"}),
    ]
    cond_edges = [
        _edge(
            "e1",
            "s1",
            "ng",
            condition={
                "from_path": "nodes.s1.output.receipt.is_published",
                "operator": "equals",
                "value": True,
            },
        ),
        _edge("e2", "s1", "ok"),
    ]
    assert _validate(cond_nodes, cond_edges) == []


def _llm_node(node_id="llm1", inputs=None, contracts=None):
    config = {
        "provider": "openai",
        "model": "gpt-test",
        "system_prompt": "Summarize.",
        "max_tokens": 1024,
        "inputs": inputs or {},
        "output_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    }
    if contracts is not None:
        config["input_flow_contracts"] = contracts
    return _node(node_id, "llm", config)


def test_llm_dict_form_flow_contract_accepts_narrative():
    """Editor dict-form entries ({"accepted_value_kinds": [...]}) are honored."""
    nodes = [
        _source_node(
            "specialist_agent", inputs={"task": "x"}, target={"agent_id": "a1"}
        ),
        _llm_node(
            inputs={"report": _ref("nodes.s1.output.narrative.text")},
            contracts={"report": {"accepted_value_kinds": ["structured", "narrative"]}},
        ),
        _node("done", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "s1", "llm1"), _edge("e2", "llm1", "done")]
    assert _validate(nodes, edges) == []


def test_llm_without_flow_contract_rejects_narrative():
    nodes = [
        _source_node(
            "specialist_agent", inputs={"task": "x"}, target={"agent_id": "a1"}
        ),
        _llm_node(inputs={"report": _ref("nodes.s1.output.narrative.text")}),
        _node("done", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "s1", "llm1"), _edge("e2", "llm1", "done")]
    errors = _validate(nodes, edges)
    assert any(e.startswith("flow_contract:") for e in errors), errors


def test_agent_node_rejects_narrative():
    """Agent Nodes stay structured-only; narrative declassifies via LLM Nodes."""
    nodes = [
        _source_node(
            "specialist_agent", inputs={"task": "x"}, target={"agent_id": "a1"}
        ),
        _node(
            "ag",
            "agent",
            {
                "agent_id": "agent_x",
                "inputs": {"context": _ref("nodes.s1.output.narrative.text")},
                "output_schema": {"type": "object", "properties": {}},
            },
        ),
        _node("done", "terminal", {"outcome": "success"}),
    ]
    edges = [_edge("e1", "s1", "ag"), _edge("e2", "ag", "done")]
    errors = _validate(nodes, edges)
    assert any(e.startswith("flow_contract:") for e in errors), errors


# --- adapters --------------------------------------------------------------


def _setup_mock_specialist(monkeypatch, final_text="specialist result"):
    monkeypatch.setattr(
        agent_store, "get_agent", lambda agent_id: {"agent_id": agent_id}
    )
    monkeypatch.setattr(
        agent_store,
        "create_session",
        lambda agent_id, title=None, source=None: {"session_id": "asess_1"},
    )
    monkeypatch.setattr(
        agent_store,
        "start_queued_run",
        lambda session_id, content, created_instance_id=None: (
            {"message_id": "m1"},
            {"run_id": "arun_1"},
        ),
    )
    monkeypatch.setattr(
        agent_store,
        "get_run",
        lambda run_id: {
            "run_id": run_id,
            "status": "succeeded",
            "session_id": "asess_1",
            "assistant_message_id": "amsg_1",
        },
    )
    monkeypatch.setattr(
        agent_store,
        "get_message",
        lambda message_id: (
            {"message_id": message_id, "content": final_text}
            if final_text is not None
            else None
        ),
    )
    monkeypatch.setattr(
        "obsidian_ai_hub.tasks.adapters.agent.wait_for_child_run",
        lambda task_id, get_run, cancel, terminal, poll, timeout, **kwargs: {
            "run_id": "arun_1",
            "status": "succeeded",
            "session_id": "asess_1",
            "assistant_message_id": "amsg_1",
        },
    )
    monkeypatch.setattr(
        task_store, "set_active_child", lambda task_id, child_kind, child_run_id, conn=None: None
    )
    monkeypatch.setattr(
        task_store, "append_task_event", lambda task_id, event_type, payload, conn=None: None
    )


def _specialist_step():
    return {
        "capability_key": "specialist_agent",
        "target": {"agent_id": "agent_1"},
        "inputs": {"task": "analyze"},
    }


def test_specialist_adapter_publishes_receipt_and_narrative(monkeypatch):
    _setup_mock_specialist(monkeypatch, final_text="The specialist analysis.")
    task = {"task_id": "t1"}
    plan = {"plan": {"purpose": "p", "completion_criteria": "c"}}

    result = AgentAdapter().execute_step(task, plan, 0, _specialist_step())

    assert result.needs_attention is False
    assert result.output["receipt"] == {
        "status": "completed",
        "child_run_id": "arun_1",
        "session_id": "asess_1",
        "agent_id": "agent_1",
    }
    assert result.output["narrative"] == {"text": "The specialist analysis."}
    assert result.child_kind == "agent"
    assert result.child_run_id == "arun_1"


def test_specialist_adapter_missing_message_needs_attention(monkeypatch):
    _setup_mock_specialist(monkeypatch, final_text=None)
    task = {"task_id": "t1"}
    plan = {"plan": {"purpose": "p", "completion_criteria": "c"}}

    result = AgentAdapter().execute_step(task, plan, 0, _specialist_step())

    assert result.needs_attention is True
    assert result.attention_reason == "specialist_report_unresolvable"
    assert result.child_run_id == "arun_1"
    assert result.output["receipt"]["status"] == "completed"
    assert result.output["narrative"] == {"text": ""}
    assert result.error


def _setup_mock_research(monkeypatch, markdown="# Findings\n\nbody"):
    def create(theme, mode="auto", context=None, output_style=None, project_id=None):
        theme_rec = research_db.create_theme(
            theme=theme,
            kind="explore",
            confidence=1.0,
            status="candidate",
            project_id=project_id,
        )
        job = research_db.create_job(theme_rec["theme_id"], project_id=project_id)
        return theme_rec, job

    def submit(theme_id, job_id, mode="auto", output_style=None, context=None):
        research_db.update_job(
            job_id,
            status="succeeded",
            generated_title="Mixed Title",
            mode=mode,
            markdown=markdown,
            is_published=1,
            error=None,
        )

    monkeypatch.setattr(research_runner, "get_or_create_theme_and_job", create)
    monkeypatch.setattr(research_runner, "submit_research_job_bg", submit)


def _research_step(theme="mixed theme"):
    return {
        "capability_key": "research_agent",
        "target": {},
        "inputs": {"theme": theme},
    }


def test_research_adapter_publishes_receipt_and_narrative(
    test_memory_db_path, monkeypatch
):
    _setup_mock_research(monkeypatch, markdown="# Findings\n\nbody text")
    task = task_store.create_task("research contract check")
    plan = {"plan": {"purpose": "p", "completion_criteria": "c"}}

    result = ResearchAdapter(poll_interval=0.01).execute_step(
        task, plan, 0, _research_step()
    )

    assert result.needs_attention is False
    receipt = result.output["receipt"]
    assert receipt["status"] == "completed"
    assert receipt["job_id"] == result.child_run_id
    assert receipt["theme_id"]
    assert receipt["is_published"] is True
    assert result.output["narrative"] == {"text": "# Findings\n\nbody text"}
    assert result.child_kind == "research"


def test_research_adapter_missing_report_needs_attention(
    test_memory_db_path, monkeypatch
):
    _setup_mock_research(monkeypatch, markdown="   ")
    task = task_store.create_task("research missing report")
    plan = {"plan": {"purpose": "p", "completion_criteria": "c"}}

    result = ResearchAdapter(poll_interval=0.01).execute_step(
        task, plan, 0, _research_step()
    )

    assert result.needs_attention is True
    assert result.attention_reason == "research_report_unresolvable"
    assert result.child_run_id
    assert result.output["receipt"]["status"] == "completed"
    assert result.output["narrative"] == {"text": ""}
    assert result.error


# --- end-to-end ------------------------------------------------------------


def test_specialist_narrative_to_template_to_vault_file_write(
    tmp_path, test_memory_db_path, monkeypatch
):
    """Specialist narrative -> Text Template -> vault_write_file.content."""
    _setup_mock_specialist(monkeypatch, final_text="The specialist analysis.")
    _patch_vault(monkeypatch, tmp_path)

    nodes = [
        _node(
            "spec1",
            "capability",
            {
                "capability_key": "specialist_agent",
                "target": {"agent_id": "agent_1"},
                "inputs": {"task": "analyze"},
            },
        ),
        _node(
            "tmpl1",
            "text_template",
            {
                "inputs": {"report": _ref("nodes.spec1.output.narrative.text")},
                "template": "# Analysis\n\n{{ report }}",
            },
        ),
        _node(
            "write1",
            "capability",
            {
                "capability_key": "vault_write_file",
                "inputs": {
                    "vault_id": "blog",
                    "relative_path": "specialist-summary.md",
                    "content": _ref("nodes.tmpl1.output.text"),
                },
            },
        ),
        _node("done", "terminal", {"outcome": "success"}),
    ]
    edges = [
        _edge("e1", "spec1", "tmpl1"),
        _edge("e2", "tmpl1", "write1"),
        _edge("e3", "write1", "done"),
    ]
    assert _validate(nodes, edges) == []

    wf = workflow_store.create_workflow("mixed-specialist-wf", skip_approval=True)
    rev = wf["revision"]
    workflow_store.set_revision_graph(rev["revision_id"], nodes, edges)
    workflow_store.publish_revision(rev["revision_id"])

    workflow_store.create_run(wf["workflow_id"], rev["revision_id"], {})
    run = workflow_store.claim_run("test-instance")
    assert run is not None

    outcome = WorkflowEngine(DefaultNodeRunner(poll_interval=0.01)).execute(run)
    assert outcome.kind == "completed"

    written_file = Path(vault_service.config.VAULT_PATH) / "specialist-summary.md"
    assert written_file.exists()
    assert (
        written_file.read_text("utf-8") == "# Analysis\n\nThe specialist analysis."
    )


def test_research_narrative_to_template_to_vault_file_write(
    tmp_path, test_memory_db_path, monkeypatch
):
    """Research narrative -> Text Template -> vault_write_file.content."""
    _setup_mock_research(monkeypatch, markdown="# Findings\n\nbody text")
    _patch_vault(monkeypatch, tmp_path)

    nodes = [
        _node(
            "res1",
            "capability",
            {
                "capability_key": "research_agent",
                "inputs": {"theme": "mixed research theme"},
            },
        ),
        _node(
            "tmpl1",
            "text_template",
            {
                "inputs": {"report": _ref("nodes.res1.output.narrative.text")},
                "template": "# Research\n\n{{ report }}",
            },
        ),
        _node(
            "write1",
            "capability",
            {
                "capability_key": "vault_write_file",
                "inputs": {
                    "vault_id": "blog",
                    "relative_path": "research-summary.md",
                    "content": _ref("nodes.tmpl1.output.text"),
                },
            },
        ),
        _node("done", "terminal", {"outcome": "success"}),
    ]
    edges = [
        _edge("e1", "res1", "tmpl1"),
        _edge("e2", "tmpl1", "write1"),
        _edge("e3", "write1", "done"),
    ]
    assert _validate(nodes, edges) == []

    wf = workflow_store.create_workflow("mixed-research-wf", skip_approval=True)
    rev = wf["revision"]
    workflow_store.set_revision_graph(rev["revision_id"], nodes, edges)
    workflow_store.publish_revision(rev["revision_id"])

    workflow_store.create_run(wf["workflow_id"], rev["revision_id"], {})
    run = workflow_store.claim_run("test-instance")
    assert run is not None

    outcome = WorkflowEngine(DefaultNodeRunner(poll_interval=0.01)).execute(run)
    assert outcome.kind == "completed"

    written_file = Path(vault_service.config.VAULT_PATH) / "research-summary.md"
    assert written_file.exists()
    assert written_file.read_text("utf-8") == "# Research\n\n# Findings\n\nbody text"
