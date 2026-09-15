import json
from unittest.mock import MagicMock, patch
import pytest

from obsidian_ai_hub.agents import registry, runtime, store


def test_agent_delegate_catalog_and_resolution():
    tools = registry.list_available_tools()
    tool_ids = [t["tool_id"] for t in tools]
    assert "agent_delegate" in tool_ids

    resolved = registry.resolve_tools(["agent_delegate"])
    assert len(resolved) == 1
    assert resolved[0].name == "agent_delegate"


def test_agent_delegate_without_context_fails():
    tool_obj = registry.resolve_tools(["agent_delegate"])[0]
    res_str = tool_obj.invoke({"agent_id": "agent_target", "task": "something"})
    res = json.loads(res_str)
    assert res["status"] == "failed"
    assert "コンテキストが無いため" in res["error"]


def test_agent_delegate_coding_context_without_agent_id_fails():
    # The coding orchestrator binds trusted_ctx with only repo_path/backend_name
    # (no agent run context). agent_delegate must refuse this context instead of
    # attempting a delegation whose parent agent id is empty.
    ctx = {"repo_path": "/tmp/repo", "backend_name": "codex"}
    tool_obj = registry.resolve_tools_with_context(["agent_delegate"], ctx)[0]
    res_str = tool_obj.invoke({"agent_id": "agent_target", "task": "something"})
    res = json.loads(res_str)
    assert res["status"] == "failed"
    assert "コンテキストが無いため" in res["error"]


def test_agent_delegate_tool_with_agent_context_succeeds():
    # AI-agent tool-call path: trusted_ctx carries the parent agent_id, so the
    # context guard must not block the delegation.
    child = store.create_agent(
        name="Child Tool",
        system_prompt="Child prompt",
        tool_ids=["web_search"],
    )
    parent = store.create_agent(
        name="Parent Tool",
        system_prompt="Parent prompt",
        tool_ids=["agent_delegate"],
        delegate_agent_ids=[child["agent_id"]],
    )
    trusted_ctx = {
        "agent_id": parent["agent_id"],
        "session_id": "asess_tool",
        "run_id": "arun_tool",
        "user_message_id": "amsg_tool",
        "user_content": "本物のユーザー発話",
    }
    tool_obj = registry.resolve_tools_with_context(["agent_delegate"], trusted_ctx)[0]

    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm_factory.return_value = mock_llm
        mock_ai_msg = MagicMock()
        mock_ai_msg.content = "子の最終回答テキスト"
        mock_ai_msg.tool_calls = []
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = mock_ai_msg

        res = json.loads(
            tool_obj.invoke({"agent_id": child["agent_id"], "task": "委譲タスク"})
        )

    assert res["status"] == "succeeded"
    assert res["agent_id"] == child["agent_id"]
    assert res["final_answer"] == "子の最終回答テキスト"


def test_delegate_subagent_propagates_child_agent_id_and_root_context(monkeypatch):
    # Nested delegation must propagate the child's own agent_id (so its internal
    # agent_delegate / memory tools keep a real identity) plus the root user
    # context.
    child = store.create_agent(name="Child Prop", system_prompt="Prompt")
    parent = store.create_agent(
        name="Parent Prop",
        system_prompt="Prompt",
        delegate_agent_ids=[child["agent_id"]],
    )
    captured: dict = {}

    def fake_core(agent, task, trusted_ctx, depth):
        captured["agent_id"] = agent["agent_id"]
        captured["ctx"] = dict(trusted_ctx)
        return {
            "status": "succeeded",
            "agent_id": agent["agent_id"],
            "agent_name": agent["name"],
            "depth": depth,
            "final_answer": "ok",
            "used_tools": [],
            "created_hitl_run_ids": [],
        }

    monkeypatch.setattr(runtime, "execute_subagent_core", fake_core)
    parent_ctx = {
        "agent_id": parent["agent_id"],
        "session_id": "asess_prop",
        "run_id": "arun_prop",
        "user_message_id": "amsg_prop",
        "user_content": "ルート発話",
    }

    res = runtime.delegate_subagent(child["agent_id"], "task", parent_ctx)

    assert res["status"] == "succeeded"
    assert captured["agent_id"] == child["agent_id"]
    assert captured["ctx"]["agent_id"] == child["agent_id"]
    assert captured["ctx"]["user_content"] == "ルート発話"
    assert captured["ctx"]["run_id"] == "arun_prop"


def test_agent_delegate_permission_and_self_and_cycle():
    child = store.create_agent(name="Child Deleg", system_prompt="Prompt")
    unallowed = store.create_agent(name="Unallowed Deleg", system_prompt="Prompt")
    parent = store.create_agent(
        name="Parent Deleg",
        system_prompt="Prompt",
        delegate_agent_ids=[child["agent_id"]],
    )

    trusted_ctx = {
        "agent_id": parent["agent_id"],
        "session_id": "asess_123",
        "run_id": "arun_123",
        "user_message_id": "amsg_123",
        "user_content": "ルートの質問内容",
    }

    # 1. Unallowed target
    res_unallowed = runtime.delegate_subagent(unallowed["agent_id"], "task", trusted_ctx)
    assert res_unallowed["status"] == "failed"
    assert "許可された委譲先" in res_unallowed["error"]

    # 2. Self call
    res_self = runtime.delegate_subagent(parent["agent_id"], "task", trusted_ctx)
    assert res_self["status"] == "failed"
    assert "自己呼出し" in res_self["error"]

    # 3. Cycle call
    deleg_ctx = runtime.DelegationContext(root_agent_id=parent["agent_id"])
    deleg_ctx.call_stack = [parent["agent_id"], child["agent_id"]]
    trusted_ctx_cycle = dict(trusted_ctx)
    trusted_ctx_cycle["delegation_ctx"] = deleg_ctx

    res_cycle = runtime.delegate_subagent(parent["agent_id"], "task", trusted_ctx_cycle)
    assert res_cycle["status"] == "failed"
    assert "循環委譲" in res_cycle["error"]


def test_agent_delegate_total_delegation_limit():
    child = store.create_agent(name="Child Limit", system_prompt="Prompt")
    parent = store.create_agent(
        name="Parent Limit",
        system_prompt="Prompt",
        delegate_agent_ids=[child["agent_id"]],
    )

    deleg_ctx = runtime.DelegationContext(root_agent_id=parent["agent_id"], max_total_delegations=12)
    deleg_ctx.total_delegations = 12

    trusted_ctx = {
        "agent_id": parent["agent_id"],
        "delegation_ctx": deleg_ctx,
    }

    res = runtime.delegate_subagent(child["agent_id"], "task", trusted_ctx)
    assert res["status"] == "failed"
    assert "上限（12回）" in res["error"]


def test_agent_delegate_depth_3_excludes_delegate_tool():
    # Agent at depth 3 should not have agent_delegate resolved
    great_grandchild = store.create_agent(
        name="Great Grandchild",
        system_prompt="Prompt",
        tool_ids=["web_search", "agent_delegate"],
    )

    trusted_ctx = {
        "agent_id": great_grandchild["agent_id"],
        "delegation_ctx": runtime.DelegationContext(root_agent_id="root"),
    }

    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm_factory.return_value = mock_llm
        mock_ai_msg = MagicMock()
        mock_ai_msg.content = "到達応答"
        mock_ai_msg.tool_calls = []
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = mock_ai_msg

        res = runtime.execute_subagent_core(
            agent=great_grandchild,
            task="ひ孫タスク",
            trusted_ctx=trusted_ctx,
            depth=3,
        )

        assert res["status"] == "succeeded"
        assert res["depth"] == 3
        # Check tools bound to LLM: agent_delegate must NOT be in active_tools
        bound_tools = mock_llm.bind_tools.call_args[0][0]
        bound_tool_names = [t.name for t in bound_tools]
        assert "web_search" in bound_tool_names
        assert "agent_delegate" not in bound_tool_names


def test_successful_subagent_delegation_flow_with_mocked_llm():
    child = store.create_agent(
        name="Child Worker",
        system_prompt="Child prompt",
        tool_ids=["web_search"],
    )
    parent = store.create_agent(
        name="Parent Orchestrator",
        system_prompt="Parent prompt",
        tool_ids=["agent_delegate"],
        delegate_agent_ids=[child["agent_id"]],
    )

    trusted_ctx = {
        "agent_id": parent["agent_id"],
        "session_id": "asess_1",
        "run_id": "arun_1",
        "user_message_id": "amsg_1",
        "user_content": "本物のユーザー発話",
    }

    with patch("obsidian_ai_hub.agents.runtime.create_langchain_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm_factory.return_value = mock_llm
        mock_ai_msg = MagicMock()
        mock_ai_msg.content = "子の最終回答テキスト"
        mock_ai_msg.tool_calls = []
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = mock_ai_msg

        res = runtime.delegate_subagent(
            target_agent_id=child["agent_id"],
            task="子への要約タスク",
            parent_trusted_ctx=trusted_ctx,
        )

        assert res["status"] == "succeeded"
        assert res["agent_id"] == child["agent_id"]
        assert res["agent_name"] == "Child Worker"
        assert res["depth"] == 1
        assert res["final_answer"] == "子の最終回答テキスト"
