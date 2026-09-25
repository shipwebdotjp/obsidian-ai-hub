"""Agent create CLI (``agents.cli.main_agent_create``)."""

from __future__ import annotations

import json

from obsidian_ai_hub.agents import cli


def test_main_agent_create_from_json(tmp_path, capsys):
    path = tmp_path / "agent.json"
    path.write_text(
        json.dumps(
            {
                "name": "CLI Agent",
                "system_prompt": "prompt",
                "tool_ids": ["vault_search"],
                "provider": "openai",
                "model": "gpt-6-sol",
            }
        ),
        encoding="utf-8",
    )

    assert cli.main_agent_create(str(path)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is True
    assert payload["agent"]["name"] == "CLI Agent"
    assert payload["agent"]["tool_ids"] == ["vault_search"]
    assert payload["agent"]["provider"] == "openai"


def test_main_agent_create_reports_missing_file(tmp_path, capsys):
    assert cli.main_agent_create(str(tmp_path / "missing.json")) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is False


def test_main_agent_create_reports_malformed_json(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")

    assert cli.main_agent_create(str(path)) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is False


def test_main_agent_create_reports_bad_types(tmp_path, capsys):
    path = tmp_path / "agent.json"
    path.write_text(
        json.dumps({"name": "T", "system_prompt": "p", "tool_ids": 5}),
        encoding="utf-8",
    )

    assert cli.main_agent_create(str(path)) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is False


def test_main_agent_create_reports_invalid_tool(tmp_path, capsys):
    path = tmp_path / "agent.json"
    path.write_text(
        json.dumps(
            {"name": "Bad Agent", "system_prompt": "prompt", "tool_ids": ["nope"]}
        ),
        encoding="utf-8",
    )

    assert cli.main_agent_create(str(path)) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is False
    assert "nope" in payload["error"]
