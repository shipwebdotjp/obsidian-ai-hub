# ruff: noqa: E402
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Mock macOS-specific modules before importing obsidian_ai_hub to prevent ModuleNotFoundError on Linux/CI
mock_modules = {
    "EventKit": MagicMock(),
    "AppKit": MagicMock(),
    "objc": MagicMock(),
    "Foundation": MagicMock(),
    "ApplicationServices": MagicMock(),
    "atomacos": MagicMock(),
    "Quartz": MagicMock(),
    "Vision": MagicMock(),
    "Cocoa": MagicMock(),
}
for name, m in mock_modules.items():
    sys.modules[name] = m

from obsidian_ai_hub import memory, main
from obsidian_ai_hub.utils import config


@pytest.fixture
def clean_copilot_env(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault"
    vault_path.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "VAULT_PATH", vault_path)

    # Re-register subpaths
    copilot_dir = vault_path / "copilot"
    copilot_dir.mkdir(exist_ok=True)
    (copilot_dir / "core").mkdir(exist_ok=True)
    (copilot_dir / "memory").mkdir(exist_ok=True)

    activity_dir = vault_path / "activity"
    activity_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "ACTIVITY_PATH", activity_dir)
    monkeypatch.setattr(config, "DAILY_PATH", vault_path / "daily")

    # SQLite DB temporary path configuration
    db_file = tmp_path / "memory.sqlite3"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    # Set up default prompt template
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir(exist_ok=True)
    prompt_path = prompt_dir / "memory_render.md"
    prompt_path.write_text("Prompt template text: ${memories}", encoding="utf-8")
    monkeypatch.setattr(config, "MEMORY_RENDERER_PROMPT_PATH", prompt_path)

    return vault_path


from datetime import datetime, timedelta

def test_get_currently_valid_approved_memories_basic(clean_copilot_env):
    today = datetime.now()
    past_date_str = (today - timedelta(days=10)).strftime("%Y-%m-%d")
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # Setup some candidate, rejected, expired, future, and currently valid approved memories
    m_valid = {
        "memory_id": "mem_valid",
        "status": "approved",
        "kind": "preference",
        "memory_key": "k-valid",
        "content": "Valid content",
        "valid_from": past_date_str,
        "stability": "stable"
    }
    m_candidate = {
        "memory_id": "mem_candidate",
        "status": "candidate",
        "kind": "preference",
        "memory_key": "k-cand",
        "content": "Candidate content",
        "valid_from": past_date_str,
        "stability": "stable"
    }
    m_future = {
        "memory_id": "mem_future",
        "status": "approved",
        "kind": "preference",
        "memory_key": "k-future",
        "content": "Future content",
        "valid_from": tomorrow_str,
        "stability": "stable"
    }
    m_expired = {
        "memory_id": "mem_expired",
        "status": "approved",
        "kind": "preference",
        "memory_key": "k-expired",
        "content": "Expired content",
        "valid_from": past_date_str,
        "valid_until": yesterday_str,
        "stability": "stable"
    }

    memory.save_all_memories([m_valid, m_candidate, m_future, m_expired])

    active, excluded = memory.get_currently_valid_approved_memories()

    # Verify only m_valid is returned as active
    assert len(active) == 1
    assert active[0]["memory_id"] == "mem_valid"

    # Verify that the expired and future-dated memories are in excluded list or transitioned
    expired_item = next((x for x in excluded if x["memory_id"] == "mem_expired"), None)
    assert expired_item is not None
    assert expired_item["reason"] == "expired"

    future_item = next((x for x in excluded if x["memory_id"] == "mem_future"), None)
    assert future_item is not None
    assert future_item["reason"] == "not_yet_valid"

    # Verify database was updated to transition the expired memory to 'expired' status
    mems_db = memory.load_all_memories()
    m_exp_db = next(x for x in mems_db if x["memory_id"] == "mem_expired")
    assert m_exp_db["status"] == "expired"


def test_render_copilot_profile_zero_memories(clean_copilot_env):
    # No memories in DB
    updated_files = memory.render_copilot_profile()

    # 7 files must be updated
    assert len(updated_files) == 7
    expected_rel_paths = [
        "copilot/AI_README.md",
        "copilot/core/values.md",
        "copilot/core/response_style.md",
        "copilot/core/decision_policy.md",
        "copilot/core/risk_tolerance.md",
        "copilot/core/memory_rules.md",
        "copilot/core/current_projects.md"
    ]
    for rel_path in expected_rel_paths:
        assert rel_path in updated_files
        full_path = clean_copilot_env / rel_path
        assert full_path.exists()
        content = full_path.read_text(encoding="utf-8")
        assert "type: copilot-profile" in content
        assert "現時点で承認済みメモリなし" in content


def test_render_copilot_profile_happy_path(clean_copilot_env):
    # Setup approved memory
    m_valid = {
        "memory_id": "mem_valid",
        "status": "approved",
        "kind": "preference",
        "memory_key": "k-valid",
        "content": "Prefer Python over Javascript",
        "valid_from": "2026-07-01",
        "topics": ["開発"],
        "tags": ["languages"],
        "evidence": [{"path": "some-note", "quote": "I like python"}],
        "provenance": {"extractor": "weekly-extract"},
        "stability": "stable"
    }
    memory.save_all_memories([m_valid])

    # Mock LLM response
    mock_response = """
    ```json
    {
      "AI_README.md": "## Guidelines\\nAI guidelines here",
      "values.md": "## Values\\nUser values here",
      "response_style.md": "## Response Style\\nConcise style",
      "decision_policy.md": "## Decision Policy\\nPolicy here",
      "risk_tolerance.md": "## Risk Tolerance\\nLow tolerance",
      "memory_rules.md": "## Memory Rules\\nSave code snippets",
      "current_projects.md": "## Current Projects\\nDeveloping obsidian hub"
    }
    ```
    """

    with patch("obsidian_ai_hub.memory.llm_client.generate_llm_response") as mock_llm:
        mock_llm.return_value = mock_response

        updated_files = memory.render_copilot_profile()

        # Verify LLM was called
        mock_llm.assert_called_once()
        called_kwargs = mock_llm.call_args[1]
        prompt_content = called_kwargs["prompt"]

        # Verify memory_id, evidence, and provenance were excluded from prompt to protect ID and evidence leakage
        assert "Prefer Python over Javascript" in prompt_content
        assert "mem_valid" not in prompt_content
        assert "some-note" not in prompt_content
        assert "weekly-extract" not in prompt_content

        # Verify files are successfully generated
        assert len(updated_files) == 7
        for rel_path in [
            "copilot/AI_README.md",
            "copilot/core/values.md",
            "copilot/core/response_style.md"
        ]:
            assert rel_path in updated_files
            full_path = clean_copilot_env / rel_path
            assert full_path.exists()
            content = full_path.read_text(encoding="utf-8")
            assert "type: copilot-profile" in content

        # Check a specific file content
        style_content = (clean_copilot_env / "copilot/core/response_style.md").read_text(encoding="utf-8")
        assert "Concise style" in style_content


def test_render_copilot_profile_validation_failures(clean_copilot_env):
    # Setup approved memory so LLM is called
    m_valid = {
        "memory_id": "mem_valid",
        "status": "approved",
        "kind": "preference",
        "memory_key": "k-valid",
        "content": "Prefer Python over Javascript",
        "valid_from": "2026-07-01",
        "stability": "stable"
    }
    memory.save_all_memories([m_valid])

    # 1. Malformed JSON
    with patch("obsidian_ai_hub.memory.llm_client.generate_llm_response") as mock_llm:
        mock_llm.return_value = "This is not a valid JSON string"
        with pytest.raises(ValueError, match="LLM response is not a valid JSON string"):
            memory.render_copilot_profile()

    # 2. Missing key in JSON response
    mock_missing_keys = """
    {
      "AI_README.md": "Guidelines",
      "values.md": "Values"
    }
    """
    with patch("obsidian_ai_hub.memory.llm_client.generate_llm_response") as mock_llm:
        mock_llm.return_value = mock_missing_keys
        with pytest.raises(ValueError, match="JSON key mismatch"):
            memory.render_copilot_profile()

    # 3. Empty body for a key
    mock_empty_body = """
    {
      "AI_README.md": "",
      "values.md": "Values",
      "response_style.md": "Concise style",
      "decision_policy.md": "Policy here",
      "risk_tolerance.md": "Low tolerance",
      "memory_rules.md": "Memory Rules",
      "current_projects.md": "Current Projects"
    }
    """
    with patch("obsidian_ai_hub.memory.llm_client.generate_llm_response") as mock_llm:
        mock_llm.return_value = mock_empty_body
        with pytest.raises(ValueError, match="must have a non-empty string value"):
            memory.render_copilot_profile()


def test_cli_wiring_render_copilot_profile(clean_copilot_env, monkeypatch):
    # Setup mocks for CLI invocation
    with patch("obsidian_ai_hub.memory.render_copilot_profile") as mock_render, \
         patch("sys.argv", ["main.py", "--render-copilot-profile"]):

        mock_render.return_value = ["copilot/AI_README.md", "copilot/core/values.md"]

        main.main()

        # Verify our command was triggered successfully
        mock_render.assert_called_once()
