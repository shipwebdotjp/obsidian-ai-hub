"""Single-shot LLM execution for the ``llm`` workflow node.

This is the non-conversational counterpart to the Agent Node: it sends a fixed
system prompt, the resolved ``inputs`` and the declared ``output_schema`` to one
provider/model and returns typed JSON to the graph. It binds no tools and
creates no Agent session/message/run rows, so an ``llm`` node never owns a
conversation. See ``docs/workflow/specification.md`` §3.9.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.utils import execution_logger
from obsidian_ai_hub.utils.llm_client import (
    _content_to_text,
    _extract_llm_metadata,
    _prepare_messages,
    create_langchain_llm,
)

logger = logging.getLogger(__name__)

# Providers accepted by ``create_langchain_llm``. Anything else is rejected at
# save/publish time so a node never reaches an unknown provider at run time.
LLM_PROVIDERS: tuple[str, ...] = (
    "openai",
    "gemini",
    "ollama",
    "local",
    "opencode_go",
)

# Providers whose client maps ``reasoning_effort`` (OpenAI/OpenCode Go) or
# ``reasoning`` (Ollama). Gemini/local ignore it, so the field is rejected there.
LLM_REASONING_PROVIDERS: frozenset[str] = frozenset(
    {"openai", "ollama", "opencode_go"}
)

LLM_TEMPERATURE = 0.7
LLM_SYSTEM_PROMPT_MAX_BYTES = 16 * 1024
LLM_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "provider",
        "model",
        "system_prompt",
        "max_tokens",
        "reasoning_effort",
        "inputs",
        "output_schema",
    }
)


def validate_llm_config(config: Any, *, path: str = "config") -> list[str]:
    """Validate an ``llm`` node ``config`` object.

    Rejects unknown keys (so ``retry`` and any future option cannot silently
    take effect), out-of-range values and unsupported ``reasoning_effort``
    combinations. JSON Schema validation of ``output_schema`` lives in the
    static graph validator so its errors share the Node path.
    """
    if not isinstance(config, dict):
        return [f"{path}: object が必要です"]
    errors: list[str] = []
    unknown = sorted(set(config) - LLM_CONFIG_KEYS)
    if unknown:
        errors.append(f"{path}: 未知のキー {unknown}")

    provider = config.get("provider")
    if provider not in LLM_PROVIDERS:
        errors.append(
            f"{path}.provider: {list(LLM_PROVIDERS)} のいずれかが必要です"
        )

    model = config.get("model")
    if not isinstance(model, str) or not model.strip():
        errors.append(f"{path}.model: 空でない文字列が必要です")

    system_prompt = config.get("system_prompt")
    if not isinstance(system_prompt, str):
        errors.append(f"{path}.system_prompt: 文字列が必要です")
    elif len(system_prompt.encode("utf-8")) > LLM_SYSTEM_PROMPT_MAX_BYTES:
        errors.append(
            f"{path}.system_prompt: 上限 {LLM_SYSTEM_PROMPT_MAX_BYTES} bytes を"
            "超えています"
        )

    max_tokens = config.get("max_tokens")
    if (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or max_tokens < 1
    ):
        errors.append(f"{path}.max_tokens: 正整数が必要です")

    reasoning_effort = config.get("reasoning_effort")
    if reasoning_effort is not None:
        if (
            not isinstance(reasoning_effort, str)
            or not reasoning_effort.strip()
        ):
            errors.append(f"{path}.reasoning_effort: 空でない文字列が必要です")
        elif isinstance(provider, str) and provider not in LLM_REASONING_PROVIDERS:
            errors.append(
                f"{path}.reasoning_effort: provider '{provider}' では"
                "指定できません"
            )

    inputs = config.get("inputs")
    if inputs is not None and not isinstance(inputs, dict):
        errors.append(f"{path}.inputs: object が必要です")
    return errors


def build_llm_content(inputs: dict[str, Any], output_schema: Any) -> str:
    """Build the JSON-only user instruction from resolved inputs and schema."""
    schema_text = json.dumps(output_schema or {}, ensure_ascii=False)
    inputs_text = json.dumps(inputs, ensure_ascii=False, default=str)
    return (
        "以下の入力と期待する JSON Schema に従って結果を生成し、"
        "JSON object のみを出力してください。\n"
        f"入力: {inputs_text}\n"
        f"期待する JSON Schema: {schema_text}\n"
        "出力は JSON 以外のテキストを含めないでください。"
    )


def generate_llm_json(
    *,
    provider: str,
    model: str,
    system_prompt: str,
    inputs: dict[str, Any],
    output_schema: Any,
    max_tokens: int,
    reasoning_effort: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Invoke the provider once and return the raw response text.

    Sends at most one request per call (no internal retry), records the same
    execution-log lifecycle as other LLM calls, and deliberately logs with
    ``run_id=None``: ``llm_call_logs.run_id`` is a CLI-only foreign key, so a
    Workflow LLM call is an independent audit row.
    """
    app_config.ensure_external_allowed("Workflow LLM node call")
    human_content = build_llm_content(inputs, output_schema)
    messages = _prepare_messages(
        provider, human_content, system_prompt=system_prompt
    )
    options: dict[str, Any] = {}
    if provider == "openai":
        # Do not let the provider retain the request (no server-side state).
        options["store"] = False
    if provider == "opencode_go" and session_id:
        # A unique per-Activation session id keeps calls from sharing a
        # conversation context.
        options["session_id"] = session_id
    llm = create_langchain_llm(
        provider=provider,
        model=model,
        temperature=LLM_TEMPERATURE,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        **options,
    )

    call_id = str(uuid.uuid4())
    prompt_for_log = (
        f"{system_prompt}\n\n{human_content}" if system_prompt else human_content
    )
    execution_logger.start_llm_call(
        call_id=call_id,
        run_id=None,
        provider=provider,
        model=model,
        temperature=LLM_TEMPERATURE,
        max_tokens=max_tokens,
        prompt=prompt_for_log,
    )
    try:
        message = llm.invoke(messages)
        prompt_tokens, completion_tokens, total_tokens, finish_reason = (
            _extract_llm_metadata(message)
        )
        response_text = _content_to_text(message.content)
        if finish_reason == "length":
            logger.warning(
                "Workflow LLM output was truncated (finish_reason=length): "
                "provider=%s model=%s max_tokens=%s; the JSON output may be "
                "incomplete.",
                provider,
                model,
                max_tokens,
            )
        execution_logger.succeed_llm_call(
            call_id=call_id,
            response=response_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=finish_reason,
        )
    except Exception as exc:
        execution_logger.fail_llm_call(call_id, exc)
        raise
    return response_text
