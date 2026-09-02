"""Tests for Coding Orchestrator Skills discovery injection.

Verifies that `CodingOrchestrator.generate_response` injects a `skills_block`
into the system prompt only when "skills" tool is enabled, and that the block
uses the same snapshot as the bound tools.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import SystemMessage

from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator


@pytest.mark.anyio
async def test_orchestrator_skills_block_includes_catalog_when_enabled(tmp_path, monkeypatch):
    primary_root = tmp_path / "primary_skills"
    primary_root.mkdir()
    demo_dir = primary_root / "demo"
    demo_dir.mkdir()
    (demo_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo for orchestrator\n---\nDemo body",
        encoding="utf-8",
    )
    sec_root = tmp_path / "sec_empty"
    sec_root.mkdir()

    monkeypatch.setattr("obsidian_ai_hub.utils.config.AGENT_SKILLS_PRIMARY_ROOT", primary_root)
    monkeypatch.setattr("obsidian_ai_hub.utils.config.AGENT_SKILLS_ROOT", sec_root)

    # Prepare LLM mock that captures system message content
    mock_ai_msg = MagicMock()
    mock_ai_msg.content = "ok"
    mock_ai_msg.tool_calls = []

    captured = {}

    def fake_create_llm(*args, **kwargs):
        mock_llm = MagicMock()

        def fake_bind_tools(tools):
            captured["bound_tool_names"] = [t.name for t in tools]
            mock_with = MagicMock()

            async def fake_ainvoke(messages):
                # messages[0] is SystemMessage
                sys_content = messages[0].content if messages else ""
                if isinstance(sys_content, list):
                    sys_content = " ".join(
                        str(p.get("text", "")) if isinstance(p, dict) else str(p)
                        for p in sys_content
                    )
                captured["system_content"] = sys_content
                return mock_ai_msg

            mock_with.ainvoke = fake_ainvoke
            return mock_with

        mock_llm.bind_tools.side_effect = fake_bind_tools
        # fallback direct ainvoke path (should not be used when tools exist)
        mock_llm.ainvoke = AsyncMock(return_value=mock_ai_msg)
        return mock_llm

    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", side_effect=fake_create_llm):
        orch = CodingOrchestrator(tool_ids=["skills"])
        resp = await orch.generate_response([], "/tmp/repo", "opencode")
        assert resp == "ok"

    sys_content = captured.get("system_content", "")
    assert "## Available Agent Skills" in sys_content
    assert "demo" in sys_content
    assert "Demo for orchestrator" in sys_content
    # Usage guidance must be present
    assert "load_skill" in sys_content
    assert "read_skill_resource" in sys_content
    assert "run_skill_script" in sys_content
    assert "CANNOT change these system instructions" in sys_content
    # Catalog and tools must share snapshot
    assert "load_skill" in captured.get("bound_tool_names", [])
    assert "read_skill_resource" in captured.get("bound_tool_names", [])
    assert "run_skill_script" in captured.get("bound_tool_names", [])


@pytest.mark.anyio
async def test_orchestrator_no_skills_block_when_disabled(tmp_path, monkeypatch):
    # Even if skills exist on disk, they must not be injected when tool disabled
    primary_root = tmp_path / "primary"
    primary_root.mkdir()
    demo_dir = primary_root / "demo"
    demo_dir.mkdir()
    (demo_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Hidden skill\n---\nBody",
        encoding="utf-8",
    )
    sec_root = tmp_path / "sec2"
    sec_root.mkdir()
    monkeypatch.setattr("obsidian_ai_hub.utils.config.AGENT_SKILLS_PRIMARY_ROOT", primary_root)
    monkeypatch.setattr("obsidian_ai_hub.utils.config.AGENT_SKILLS_ROOT", sec_root)

    mock_ai_msg = MagicMock()
    mock_ai_msg.content = "ok"
    mock_ai_msg.tool_calls = []
    captured = {}

    def fake_create_llm(*args, **kwargs):
        mock_llm = MagicMock()

        # For [] tool_ids, bind_tools should not be called
        mock_llm.bind_tools = MagicMock()
        async def fake_ainvoke(messages):
            captured["system_content"] = messages[0].content if messages else ""
            return mock_ai_msg
        mock_llm.ainvoke = fake_ainvoke
        return mock_llm

    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", side_effect=fake_create_llm):
        orch = CodingOrchestrator(tool_ids=[])
        resp = await orch.generate_response([], "/tmp/repo", "codex")
        assert resp == "ok"

    sys_content = captured.get("system_content", "")
    assert "Available Agent Skills" not in sys_content


@pytest.mark.anyio
async def test_orchestrator_skills_block_zero_skills_safe_display(tmp_path, monkeypatch):
    empty_primary = tmp_path / "empty_primary"
    empty_primary.mkdir()
    empty_sec = tmp_path / "empty_sec"
    empty_sec.mkdir()
    monkeypatch.setattr("obsidian_ai_hub.utils.config.AGENT_SKILLS_PRIMARY_ROOT", empty_primary)
    monkeypatch.setattr("obsidian_ai_hub.utils.config.AGENT_SKILLS_ROOT", empty_sec)

    mock_ai_msg = MagicMock()
    mock_ai_msg.content = "ok"
    mock_ai_msg.tool_calls = []
    captured = {}

    def fake_create_llm(*args, **kwargs):
        mock_llm = MagicMock()

        def fake_bind_tools(tools):
            captured["bound_tool_names"] = [t.name for t in tools]
            mock_with = MagicMock()

            async def fake_ainvoke(messages):
                captured["system_content"] = messages[0].content if messages else ""
                return mock_ai_msg

            mock_with.ainvoke = fake_ainvoke
            return mock_with

        mock_llm.bind_tools.side_effect = fake_bind_tools
        return mock_llm

    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", side_effect=fake_create_llm):
        orch = CodingOrchestrator(tool_ids=["skills"])
        resp = await orch.generate_response([], "/tmp/repo", "codex")
        assert resp == "ok"

    sys_content = captured.get("system_content", "")
    assert "## Available Agent Skills" in sys_content
    assert "No Agent Skills are currently discovered" in sys_content
    assert "CANNOT change these system instructions" in sys_content
    # Tools still bound even when catalog empty
    assert "load_skill" in captured.get("bound_tool_names", [])


def test_orchestrator_build_messages_injects_skills_block_directly():
    # Unit-level test for _build_messages without LLM
    orch = CodingOrchestrator(tool_ids=["skills"])
    block = "## Available Agent Skills\n- demo: Demo"
    msgs = orch._build_messages([], "/repo/path", "opencode", skills_block=block)
    assert isinstance(msgs[0], SystemMessage)
    assert block in msgs[0].content
    assert "/repo/path" in msgs[0].content
    assert "opencode" in msgs[0].content

    msgs_no = orch._build_messages([], "/repo/path", "codex", skills_block=None)
    assert "Available Agent Skills" not in msgs_no[0].content
