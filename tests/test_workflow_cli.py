"""Workflow CLI operations (``workflow/cli.py``, dispatched from main.py)."""

from __future__ import annotations

import json
from pathlib import Path

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.workflow import cli as workflow_cli
from obsidian_ai_hub.workflow import store as workflow_store


def _package() -> dict:
    return {
        "format": "obsidian-ai-hub.workflow-definition",
        "version": 1,
        "name": "cli-wf",
        "description": "cli test",
        "inputs_schema": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "enum": ["all", "technical"],
                    "default": "all",
                }
            },
            "required": ["focus"],
        },
        "nodes": [
            {
                "node_id": "ctx",
                "node_type": "capability",
                "config": {"capability_key": "research_context_snapshot", "inputs": {}},
                "parent_loop_node_id": None,
                "ui_position": None,
            },
            {
                "node_id": "end",
                "node_type": "terminal",
                "config": {"outcome": "success"},
                "parent_loop_node_id": None,
                "ui_position": None,
            },
        ],
        "edges": [
            {
                "edge_id": "e1",
                "source_node_id": "ctx",
                "target_node_id": "end",
                "edge_kind": "normal",
                "condition": None,
                "order_index": 0,
            }
        ],
    }


def _write_package(tmp_path: Path) -> Path:
    path = tmp_path / "package.json"
    path.write_text(json.dumps(_package(), ensure_ascii=False), encoding="utf-8")
    return path


def test_parse_inputs_parses_json_and_plain_strings():
    parsed = workflow_cli.parse_inputs(
        ["focus=all", "limit=3", "flag=true", "name=hello world"]
    )
    assert parsed == {"focus": "all", "limit": 3, "flag": True, "name": "hello world"}


def test_import_validate_publish_roundtrip(tmp_path, test_memory_db_path, capsys):
    task_store.sync_capabilities()
    path = _write_package(tmp_path)

    assert workflow_cli.import_package(str(path)) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["validation_errors"] == []
    revision_id = imported["revision_id"]

    assert workflow_cli.validate_revision(revision_id) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["valid"] is True
    assert validated["warnings"] == []

    assert workflow_cli.publish_revision(revision_id) == 0
    published = json.loads(capsys.readouterr().out)
    assert published["published"] is True
    assert published["status"] == "published"


def test_run_revision_fills_defaults_and_executes_locally(
    tmp_path, test_memory_db_path, capsys
):
    task_store.sync_capabilities()
    path = _write_package(tmp_path)
    workflow_cli.import_package(str(path))
    revision_id = json.loads(capsys.readouterr().out)["revision_id"]
    workflow_cli.publish_revision(revision_id)
    capsys.readouterr()

    exit_code = workflow_cli.run_revision(
        revision_id, {}, execute=True, wait=True
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["inputs"] == {"focus": "all"}
    assert [node["status"] for node in payload["nodes"]] == ["succeeded"]


def test_run_revision_rejects_invalid_inputs(
    tmp_path, test_memory_db_path, capsys
):
    task_store.sync_capabilities()
    path = _write_package(tmp_path)
    workflow_cli.import_package(str(path))
    revision_id = json.loads(capsys.readouterr().out)["revision_id"]
    workflow_cli.publish_revision(revision_id)
    capsys.readouterr()

    exit_code = workflow_cli.run_revision(revision_id, {"focus": "bogus"})
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["created"] is False
    assert payload["errors"]


def test_wait_stops_at_waiting_approval(tmp_path, test_memory_db_path, capsys):
    from obsidian_ai_hub.agents import store as agent_store

    agent = agent_store.create_agent(name="cli-wait-agent", system_prompt="p")
    package = _package()
    package["nodes"] = [
        {
            "node_id": "agent",
            "node_type": "agent",
            "config": {
                "agent_id": agent["agent_id"],
                "inputs": {},
                "output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                },
            },
            "parent_loop_node_id": None,
            "ui_position": None,
        },
        package["nodes"][1],
    ]
    package["edges"] = [
        {
            "edge_id": "e1",
            "source_node_id": "agent",
            "target_node_id": "end",
            "edge_kind": "normal",
            "condition": None,
            "order_index": 0,
        }
    ]
    path = tmp_path / "agent-wf.json"
    path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    task_store.sync_capabilities()
    workflow_cli.import_package(str(path))
    revision_id = json.loads(capsys.readouterr().out)["revision_id"]
    workflow_cli.publish_revision(revision_id)
    capsys.readouterr()

    exit_code = workflow_cli.run_revision(revision_id, {}, wait=True, timeout=5)
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "waiting_approval"


def test_import_package_reports_missing_file(tmp_path, test_memory_db_path, capsys):
    exit_code = workflow_cli.import_package(str(tmp_path / "missing.json"))
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["success"] is False


def test_validate_and_run_report_unknown_revision(test_memory_db_path, capsys):
    assert workflow_cli.validate_revision("wrev_missing") == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False

    assert workflow_cli.run_revision("wrev_missing", {}) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False


def test_run_revision_records_approval_skip_event(
    tmp_path, test_memory_db_path, capsys
):
    from obsidian_ai_hub.agents import store as agent_store

    agent = agent_store.create_agent(name="cli-skip-agent", system_prompt="p")
    package = _package()
    package["nodes"] = [
        {
            "node_id": "agent",
            "node_type": "agent",
            "config": {
                "agent_id": agent["agent_id"],
                "inputs": {},
                "output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                },
            },
            "parent_loop_node_id": None,
            "ui_position": None,
        },
        package["nodes"][1],
    ]
    package["edges"] = [
        {
            "edge_id": "e1",
            "source_node_id": "agent",
            "target_node_id": "end",
            "edge_kind": "normal",
            "condition": None,
            "order_index": 0,
        }
    ]
    path = tmp_path / "skip-wf.json"
    path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    task_store.sync_capabilities()
    workflow_cli.import_package(str(path))
    imported = json.loads(capsys.readouterr().out)
    workflow_id = imported["workflow_id"]
    revision_id = imported["revision_id"]
    workflow_store.update_workflow(workflow_id, skip_approval=True)
    workflow_cli.publish_revision(revision_id)
    capsys.readouterr()

    exit_code = workflow_cli.run_revision(revision_id, {})
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "queued"
    events = workflow_store.list_events(payload["run_id"])
    assert any(e["event_type"] == "run_approval_skipped" for e in events)


def test_publish_rejects_invalid_graph(tmp_path, test_memory_db_path, capsys):
    task_store.sync_capabilities()
    package = _package()
    package["nodes"][0]["config"]["capability_key"] = "missing_capability"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")

    assert workflow_cli.import_package(str(path)) == 1
    imported = json.loads(capsys.readouterr().out)
    assert imported["validation_errors"]
    assert workflow_cli.publish_revision(imported["revision_id"]) == 1
    published = json.loads(capsys.readouterr().out)
    assert published["published"] is False
