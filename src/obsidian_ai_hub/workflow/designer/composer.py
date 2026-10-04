"""Workflow Designer Composer engine and tool loop.

Controls LLM interaction, tool dispatch, context/turn/tool-call budgets,
llm_call_logs execution logging, and node analysis payload generation.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from obsidian_ai_hub.utils import config
from obsidian_ai_hub.utils import execution_logger
from obsidian_ai_hub.utils.llm_client import create_langchain_llm
from obsidian_ai_hub.workflow.designer import tools
from obsidian_ai_hub.workflow.designer.builder import GraphBuilder

logger = logging.getLogger(__name__)

# Budget limits
MAX_TURNS = 32
MAX_TOOL_CALLS = 128
MAX_CONTEXT_BYTES = 96 * 1024  # 96 KiB
MAX_SINGLE_RESULT_BYTES = 8 * 1024  # 8 KiB

# Exceptions


class WorkflowDesignerNotConfiguredError(RuntimeError):
    """Raised when llm.workflow_designer provider or model is not configured."""


class TurnBudgetExceededError(RuntimeError):
    """Raised when max_turns (32) is reached."""


class ToolCallBudgetExceededError(RuntimeError):
    """Raised when max_tool_calls (128) is reached."""


class ContextBudgetExceededError(RuntimeError):
    """Raised when cumulative tool result context exceeds 96 KiB."""


class ToolCallingNotSupportedError(RuntimeError):
    """Raised when the LLM model does not support tool calling."""


class WorkflowDesignerProviderError(RuntimeError):
    """Raised when the LLM provider fails."""


def _truncate_tool_result(result_str: str) -> str:
    encoded = result_str.encode("utf-8")
    if len(encoded) <= MAX_SINGLE_RESULT_BYTES:
        return result_str
    truncated_bytes = encoded[:MAX_SINGLE_RESULT_BYTES]
    return truncated_bytes.decode("utf-8", errors="ignore") + "\n... [Truncated]"


def compose_workflow_draft(
    requirement: str,
    *,
    custom_llm: Optional[Any] = None,
) -> dict[str, Any]:
    """Execute the Workflow Designer tool-loop for a user requirement.

    Returns the standardized response payload:
    {
      "package": DefinitionPackage | null,
      "summary": string | null,
      "assumptions": [string],
      "node_analysis": [NodeAnalysis],
      "structural_errors": [GraphIssue],
      "validation_issues": [GraphIssue]
    }
    """
    req_clean = (requirement or "").strip()
    if not req_clean:
        raise ValueError("requirement は空でない文字列が必要です")

    provider = config.LLM_WORKFLOW_DESIGNER_PROVIDER
    model = config.LLM_WORKFLOW_DESIGNER_MODEL

    if not custom_llm and (not provider or not model):
        raise WorkflowDesignerNotConfiguredError(
            "llm.workflow_designer の provider または model が未設定です"
        )

    prompt_path = config.LLM_WORKFLOW_DESIGNER_PROMPT_PATH
    if prompt_path and Path(prompt_path).exists():
        system_prompt = Path(prompt_path).read_text(encoding="utf-8")
    else:
        system_prompt = "あなたは Workflow Designer AI です。GraphBuilder ツールを使ってグラフを作成してください。"

    builder = GraphBuilder()
    designer_tools = tools.create_designer_tools(builder)
    tools_by_name = {t.name: t for t in designer_tools}

    if custom_llm is not None:
        llm = custom_llm
    else:
        try:
            llm = create_langchain_llm(
                provider=provider,
                model=model,
                temperature=0.2,
                max_tokens=4096,
            )
        except Exception as exc:
            logger.exception("LLM の初期化に失敗しました")
            raise WorkflowDesignerProviderError("LLM プロバイダの初期化に失敗しました") from exc

    try:
        llm_with_tools = llm.bind_tools(designer_tools)
    except Exception as exc:
        logger.exception("ツールバインディングに失敗しました")
        raise ToolCallingNotSupportedError(f"選択されたモデル '{model}' は tool calling に対応していません") from exc

    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"以下の要件を満たす Workflow グラフを下書き・構築してください:\n\n{req_clean}"),
    ]

    turns = 0
    total_tool_calls = 0
    cumulative_context_bytes = 0
    final_payload: Optional[dict[str, Any]] = None

    while turns < MAX_TURNS:
        if cumulative_context_bytes > MAX_CONTEXT_BYTES:
            raise ContextBudgetExceededError("累積ツール結果コンテキスト上限 (96 KiB) を超えました")

        turns += 1
        call_id = f"wfd_{uuid.uuid4().hex[:12]}"

        # Start LLM call log
        execution_logger.start_llm_call(
            call_id=call_id,
            run_id=None,
            provider=provider or "custom",
            model=model or "custom",
            temperature=0.2,
            max_tokens=4096,
            prompt=req_clean if turns == 1 else f"Turn {turns}",
            system_prompt=system_prompt,
        )

        try:
            ai_msg = llm_with_tools.invoke(messages)
        except Exception as exc:
            execution_logger.fail_llm_call(call_id=call_id, exc=exc)
            logger.exception("LLM 呼び出しに失敗しました")
            raise WorkflowDesignerProviderError("LLM プロバイダの呼び出しに失敗しました") from exc

        # Collect response metadata
        token_usage = getattr(ai_msg, "usage_metadata", None) or {}
        p_tokens = token_usage.get("input_tokens")
        c_tokens = token_usage.get("output_tokens")
        t_tokens = token_usage.get("total_tokens")

        tool_calls_data = getattr(ai_msg, "tool_calls", None) or []
        formatted_tool_calls = [
            {"id": tc.get("id"), "name": tc.get("name"), "args": tc.get("args")}
            for tc in tool_calls_data
        ]

        execution_logger.succeed_llm_call(
            call_id=call_id,
            response=str(ai_msg.content or ""),
            prompt_tokens=p_tokens,
            completion_tokens=c_tokens,
            total_tokens=t_tokens,
            finish_reason="tool_calls" if tool_calls_data else "stop",
            tool_calls=formatted_tool_calls if formatted_tool_calls else None,
        )

        messages.append(ai_msg)

        if not tool_calls_data:
            # LLM completed turn without calling further tools.
            # A package is only returned when the LLM explicitly finalized
            # via the graph_finalize tool; otherwise no draft can be created.
            # When the builder holds a graph (e.g. graph_finalize was called
            # but rejected for structural errors), surface the actual errors
            # instead of a generic finalize_not_called.
            if final_payload is None:
                if builder.nodes:
                    val = builder.validate()
                    if val["structural_errors"]:
                        return {
                            "package": None,
                            "summary": None,
                            "assumptions": [],
                            "node_analysis": [],
                            "structural_errors": val["structural_errors"],
                            "validation_issues": val["validation_issues"],
                        }
                    return {
                        "package": None,
                        "summary": None,
                        "assumptions": [],
                        "node_analysis": [],
                        "structural_errors": [
                            {
                                "code": "finalize_not_called",
                                "message": "graph_finalize が呼ばれずに終了したため package を返しません",
                            }
                        ],
                        "validation_issues": [],
                    }
                raise WorkflowDesignerProviderError("LLM がツールを呼び出さずに応答を終了しました")
            break

        total_tool_calls += len(tool_calls_data)
        if total_tool_calls > MAX_TOOL_CALLS:
            raise ToolCallBudgetExceededError("累積ツール呼び出し回数上限 (128) を超えました")

        logged_tool_calls: list[dict[str, Any]] = []
        for tc in tool_calls_data:
            t_name = tc.get("name")
            t_args = tc.get("args") or {}
            t_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"

            tool_inst = tools_by_name.get(t_name)
            if not tool_inst:
                res_obj = {"ok": False, "code": "tool_not_found", "message": f"ツール '{t_name}' が存在しません"}
                logged_entry = {
                    "call_id": t_id,
                    "provider_call_id": tc.get("id"),
                    "tool_name": str(t_name or ""),
                    "args": t_args,
                    "status": "failed",
                    "error": f"ツール '{t_name}' が存在しません",
                }
            else:
                try:
                    res_obj = tool_inst.invoke(t_args)
                    logged_entry = {
                        "call_id": t_id,
                        "provider_call_id": tc.get("id"),
                        "tool_name": str(t_name or ""),
                        "args": t_args,
                        "status": "succeeded",
                        "result": res_obj,
                    }
                except Exception as exc:
                    res_obj = {"ok": False, "code": "tool_execution_error", "message": str(exc)}
                    logged_entry = {
                        "call_id": t_id,
                        "provider_call_id": tc.get("id"),
                        "tool_name": str(t_name or ""),
                        "args": t_args,
                        "status": "failed",
                        "error": str(exc),
                    }
            logged_tool_calls.append(logged_entry)

            res_json = json.dumps(res_obj, ensure_ascii=False)
            res_truncated = _truncate_tool_result(res_json)
            res_bytes = len(res_truncated.encode("utf-8"))

            cumulative_context_bytes += res_bytes
            if cumulative_context_bytes > MAX_CONTEXT_BYTES:
                raise ContextBudgetExceededError("累積ツール結果コンテキスト上限 (96 KiB) を超えました")

            messages.append(ToolMessage(content=res_truncated, tool_call_id=t_id))

            if t_name == "graph_finalize" and isinstance(res_obj, dict) and res_obj.get("ok"):
                final_payload = res_obj
                break

        # Persist per-turn tool args/results (masked, capped) to the call log.
        execution_logger.update_llm_call_tool_calls(call_id, logged_tool_calls)

        if final_payload is not None:
            break

    if turns >= MAX_TURNS and final_payload is None:
        raise TurnBudgetExceededError("ターン数上限 (32) を超えました")

    assert final_payload is not None

    return {
        "package": final_payload.get("package"),
        "summary": final_payload.get("summary"),
        "assumptions": final_payload.get("assumptions") or [],
        "node_analysis": final_payload.get("node_analysis") or [],
        "structural_errors": final_payload.get("structural_errors") or [],
        "validation_issues": final_payload.get("validation_issues") or [],
    }
