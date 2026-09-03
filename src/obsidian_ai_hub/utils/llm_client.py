import base64
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Sequence, Tuple, Optional
import logging

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
    BaseMessage,
    SystemMessage,
)
from langchain_core.tools import BaseTool
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

OPENCODE_SESSION_HEADER = "x-opencode-session"
OPENCODE_SESSION_ID_FALLBACK = "obsidian-ai-hub"


def _opencode_default_headers(
    extra: dict[str, Any] | None = None,
) -> dict[str, str]:
    """OpenCode Go 用の default_headers を返す。

    安全で安定した識別子のみを使い、APIキー・ユーザー入力・プロンプト・
    個人情報は含めない。呼び出し側の既存 default_headers は保持し、
    不足分としてセッションヘッダーを補う。
    """
    session_id = (
        str(getattr(config, "OPENCODE_SESSION_ID", "") or "").strip()
        or OPENCODE_SESSION_ID_FALLBACK
    )
    merged = dict(extra or {})
    merged.setdefault(OPENCODE_SESSION_HEADER, session_id)
    return merged


def _is_network_error(exc: Exception) -> bool:
    """
    ネットワーク系の一時的な失敗だけをリトライ対象にする。
    ライブラリごとの差異があるため、一般的な接続/タイムアウト/一時エラー名を広めに拾う。
    """
    network_error_types = (
        TimeoutError,
        ConnectionError,
        OSError,
    )
    return isinstance(exc, network_error_types)


def _with_exponential_backoff(
    func, *, max_attempts: int = 3, initial_delay: float = 1.0
):
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts or not _is_network_error(exc):
                raise

            delay = initial_delay * (2 ** (attempt - 1))
            time.sleep(delay)

    if last_error is not None:
        raise last_error
    raise RuntimeError("LLM request failed unexpectedly")


def _content_to_stream_delta(content: Any) -> str:
    """Return displayable message content without changing token boundaries.

    Unlike :func:`_content_to_text`, this helper deliberately preserves leading
    and trailing whitespace.  A streamed chunk can be a single space or a
    punctuation suffix, so trimming it would make the live response differ
    from the final persisted response.
    """
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text is not None:
                    parts.append(str(text))
        return "".join(parts)

    return str(content)


def _content_to_text(content: Any) -> str:
    """
    LangChain の AIMessage.content は str のこともあれば、
    provider によって list[dict] 形式になることもあるため、文字列化する。
    """
    return _content_to_stream_delta(content).strip()


def _prepare_messages(
    provider: str,
    prompt: str,
    files: Sequence[Path | str] | None = None,
    system_prompt: str | None = None,
) -> list[BaseMessage]:
    """
    画像を含むマルチモーダルメッセージを構築する。
    """
    messages: list[BaseMessage] = []
    if system_prompt and provider != "local":
        messages.append(SystemMessage(content=system_prompt))

    if provider == "local":
        logger.warning(
            "Multimodal is not supported for provider 'local'. Using prompt only."
        )
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        messages.append(HumanMessage(content=full_prompt))
        return messages

    if not files:
        messages.append(HumanMessage(content=prompt))
        return messages

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

    for f in files:
        p = Path(f)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {f}")

        mime_type, _ = mimetypes.guess_type(str(p))
        if not mime_type:
            mime_type = "application/octet-stream"

        with open(p, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")

        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{encoded_string}"},
            }
        )

    messages.append(HumanMessage(content=content))
    return messages


def _extract_llm_metadata(
    message: Any,
) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[str]]:
    prompt_tokens = None
    completion_tokens = None
    total_tokens = None
    finish_reason = None

    # Try usage_metadata if present
    usage = getattr(message, "usage_metadata", None)
    if isinstance(usage, dict):
        prompt_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
        completion_tokens = usage.get("output_tokens") or usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")

    # Try response_metadata if present
    meta = getattr(message, "response_metadata", None) or {}
    if isinstance(meta, dict):
        finish_reason = meta.get("finish_reason")
        if (
            not finish_reason
            and "choices" in meta
            and isinstance(meta["choices"], list)
            and len(meta["choices"]) > 0
        ):
            choice = meta["choices"][0]
            if isinstance(choice, dict):
                finish_reason = choice.get("finish_reason")

        token_usage = meta.get("token_usage")
        if isinstance(token_usage, dict):
            if prompt_tokens is None:
                prompt_tokens = token_usage.get("prompt_tokens") or token_usage.get(
                    "input_tokens"
                )
            if completion_tokens is None:
                completion_tokens = token_usage.get(
                    "completion_tokens"
                ) or token_usage.get("output_tokens")
            if total_tokens is None:
                total_tokens = token_usage.get("total_tokens")

    def safe_int(v):
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    return (
        safe_int(prompt_tokens),
        safe_int(completion_tokens),
        safe_int(total_tokens),
        finish_reason,
    )


def _logged_invoke(
    llm: Any,
    messages: list,
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
    prompt_for_log: str,
) -> Any:
    import uuid
    from obsidian_ai_hub.utils import execution_logger

    call_id = str(uuid.uuid4())
    run_id = execution_logger.current_run_id.get()

    execution_logger.start_llm_call(
        call_id=call_id,
        run_id=run_id,
        provider=provider,
        model=model,
        temperature=temperature,
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
                "LLM output was truncated (finish_reason=length): provider=%s model=%s "
                "max_tokens=%s; the response may be incomplete.",
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
        return message
    except Exception as e:
        execution_logger.fail_llm_call(call_id, e)
        raise


def _ai_message_from_chunk(chunk: AIMessageChunk) -> AIMessage:
    """Convert an aggregated stream chunk into the normal agent message type."""
    payload = chunk.model_dump()
    payload["type"] = "ai"
    return AIMessage(**payload)


async def _logged_astream(
    llm: Any,
    messages: list,
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
    prompt_for_log: str,
) -> AsyncGenerator[AIMessageChunk, None]:
    """Stream an LLM call while recording the same execution-log lifecycle.

    The caller receives each ``AIMessageChunk`` immediately.  This wrapper
    independently aggregates those chunks so the execution log is completed
    with the final content, usage and finish reason only after the provider
    stream has finished successfully.
    """
    import uuid
    from obsidian_ai_hub.utils import execution_logger

    call_id = str(uuid.uuid4())
    run_id = execution_logger.current_run_id.get()

    execution_logger.start_llm_call(
        call_id=call_id,
        run_id=run_id,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        prompt=prompt_for_log,
    )

    aggregate: AIMessageChunk | None = None
    try:
        try:
            stream = llm.astream(messages)
        except AttributeError as exc:
            raise RuntimeError(
                f"LLM provider '{provider}' model '{model}' does not support async token streaming."
            ) from exc

        async for chunk in stream:
            if not isinstance(chunk, AIMessageChunk):
                raise RuntimeError(
                    f"LLM provider '{provider}' model '{model}' returned an unsupported stream chunk "
                    f"type: {type(chunk).__name__}."
                )
            aggregate = chunk if aggregate is None else aggregate + chunk
            yield chunk

        if aggregate is None:
            raise RuntimeError(
                f"LLM provider '{provider}' model '{model}' completed without an AI message chunk."
            )

        prompt_tokens, completion_tokens, total_tokens, finish_reason = (
            _extract_llm_metadata(aggregate)
        )
        response_text = _content_to_stream_delta(aggregate.content)

        if finish_reason == "length":
            logger.warning(
                "LLM output was truncated (finish_reason=length): provider=%s model=%s "
                "max_tokens=%s; the response may be incomplete.",
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


def generate_llm_response(
    provider: str,
    model: str,
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 16384,
    files: Sequence[Path | str] | None = None,
    system_prompt: str | None = None,
) -> str:
    """
    指定のモデルとプロンプトで OpenAI/Gemini/Local/Ollama を呼び出し、
    生成されたテキストを返す。

    既存コードとの互換性のため、戻り値は str のままにしている。
    """
    config.ensure_external_allowed("LLM API call")
    messages = _prepare_messages(provider, prompt, files, system_prompt=system_prompt)
    logger.info(f"Prepared messages for LLM: {messages}")
    llm = create_langchain_llm(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    def _call() -> str:
        message = _logged_invoke(
            llm, messages, provider, model, temperature, max_tokens, prompt
        )
        logger.info(f"LLM response: {message}")
        return _content_to_text(message.content)

    return _with_exponential_backoff(_call)


def generate_llm_response_with_tools(
    provider: str,
    model: str,
    prompt: str,
    tools: Sequence[BaseTool],
    temperature: float = 0.7,
    max_tokens: int = 16384,
    max_iterations: int = 10,
    files: Sequence[Path | str] | None = None,
    system_prompt: str | None = None,
) -> str:
    """
    ツール呼び出しをサポートしたLLMレスポンス生成。
    LLMがツール呼び出しを要求する限りループし、最終的なテキスト回答を返す。
    """
    config.ensure_external_allowed("LLM API call with tools")
    messages = _prepare_messages(provider, prompt, files, system_prompt=system_prompt)

    openai_tool_options = {}
    if provider == "openai":
        openai_tool_options = {
            "use_responses_api": True,
            "store": False,
        }

    llm = create_langchain_llm(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        **openai_tool_options,
    )

    llm_with_tools = llm.bind_tools(list(tools))
    tools_by_name = {tool.name: tool for tool in tools}

    iterations = 0
    while iterations < max_iterations:
        iterations += 1

        def _call():
            return _logged_invoke(
                llm_with_tools,
                messages,
                provider,
                model,
                temperature,
                max_tokens,
                prompt,
            )

        ai_msg = _with_exponential_backoff(_call)
        messages.append(ai_msg)

        tool_calls = getattr(ai_msg, "tool_calls", None)
        if not tool_calls:
            return _content_to_text(ai_msg.content)

        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            if tool_name not in tools_by_name:
                raise RuntimeError(f"Unknown tool called by LLM: {tool_name}")

            result = tools_by_name[tool_name].invoke(tool_call["args"])
            logger.debug(
                f"Tool called: {tool_name} with args {tool_call['args']} returned result: {result}"
            )
            messages.append(
                ToolMessage(
                    content=json.dumps({"result": result}, ensure_ascii=False),
                    tool_call_id=tool_call["id"],
                )
            )

    # If we reached max_iterations and the last message still requested tool calls,
    # we need one final LLM call without tool binding to get a summary response.
    def _final_call():
        return _logged_invoke(
            llm, messages, provider, model, temperature, max_tokens, prompt
        )

    final_ai_msg = _with_exponential_backoff(_final_call)
    return _content_to_text(final_ai_msg.content)


def create_langchain_llm(
    provider: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 512,
    *,
    use_responses_api: bool | None = None,
    store: bool | None = None,
    reasoning_effort: str | None = None,
):
    """
    provider 名から LangChain の ChatModel / LLM を生成する。

    - openai: ChatOpenAI
    - gemini: ChatGoogleGenerativeAI
    - ollama: ChatOllama
    - local: LlamaCpp
    - opencode_go: ChatOpenAI / ChatAnthropic

    max_tokens: ChatOpenAI では alias により max_completion_tokens /
      Responses API では max_output_tokens へ自動マッピングされる。
      Ollama では num_predict へマッピングされる。
    reasoning_effort: ChatOpenAI では reasoning_effort (Responses APIでは
      reasoning.effort へ正規化)、Ollama では reasoning へマッピング。
    """
    cleaned_effort = reasoning_effort.strip() if isinstance(reasoning_effort, str) and reasoning_effort.strip() else None

    if provider == "openai":
        openai_options: dict[str, Any] = {}
        if use_responses_api is not None:
            openai_options["use_responses_api"] = use_responses_api
        if store is not None:
            openai_options["store"] = store
        if cleaned_effort is not None:
            openai_options["reasoning_effort"] = cleaned_effort
        return create_openai_llm(model, temperature, max_tokens, **openai_options)

    if provider == "gemini":
        return create_gemini_llm(model, temperature, max_tokens)

    if provider == "ollama":
        ollama_options: dict[str, Any] = {}
        if cleaned_effort is not None:
            ollama_options["reasoning"] = cleaned_effort
        return create_ollama_llm(model, temperature, max_tokens, **ollama_options)

    if provider == "local":
        return create_local_llama_llm(model, temperature, max_tokens)

    if provider == "opencode_go":
        opencode_options: dict[str, Any] = {}
        if cleaned_effort is not None:
            opencode_options["reasoning_effort"] = cleaned_effort
        return create_opencode_go_llm(model, temperature, max_tokens, **opencode_options)

    raise ValueError(f"Unknown provider: {provider}")


def create_opencode_go_llm(
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 512,
    *,
    reasoning_effort: str | None = None,
    default_headers: dict[str, Any] | None = None,
):
    """OpenCode Go 用 LangChain ChatModel を返す。"""
    api_key = config.OPENCODE_API_KEY
    if not api_key:
        raise RuntimeError("Environment variable OPENCODE_API_KEY is not set")

    openai_prefixes = ("gpt-", "glm-", "kimi-", "deepseek-", "mimo-", "grok-")
    anthropic_prefixes = ("minimax-", "qwen3.7-", "qwen3.6-")

    if model.startswith(openai_prefixes):
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise RuntimeError(
                "langchain-openai is required for provider 'opencode_go' with OpenAI-compatible models. "
                "Install with: pip install -U langchain-openai"
            )
        options: dict[str, Any] = {}
        if model.startswith("gpt-"):
            options["use_responses_api"] = True
        if reasoning_effort is not None:
            options["reasoning_effort"] = reasoning_effort
        options["default_headers"] = _opencode_default_headers(default_headers)

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url="https://opencode.ai/zen/go/v1",
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=0,
            **options,
        )
    elif model.startswith(anthropic_prefixes):
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise RuntimeError(
                "langchain-anthropic is required for provider 'opencode_go' with Anthropic-compatible models. "
                "Install with: pip install -U langchain-anthropic"
            )
        return ChatAnthropic(
            model=model,
            anthropic_api_key=api_key,
            base_url="https://opencode.ai/zen/go/v1",
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=0,
        )
    else:
        raise RuntimeError(f"Unsupported model ID for opencode_go: {model}")


def create_openai_llm(
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 512,
    *,
    use_responses_api: bool | None = None,
    store: bool | None = None,
    reasoning_effort: str | None = None,
):
    """OpenAI 用 LangChain ChatModel を返す。"""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise RuntimeError(
            "langchain-openai is required for provider 'openai'. "
            "Install with: pip install -U langchain-openai"
        )

    api_key = config.OPENAI_API_KEY
    if not api_key:
        raise RuntimeError("Environment variable OPENAI_API_KEY is not set")

    options: dict[str, Any] = {}
    if use_responses_api is not None:
        options["use_responses_api"] = use_responses_api
    if store is not None:
        options["store"] = store
    if reasoning_effort is not None:
        options["reasoning_effort"] = reasoning_effort

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=0,  # 外側の _with_exponential_backoff に任せる
        **options,
    )


def create_gemini_llm(model: str, temperature: float = 0.7, max_tokens: int = 512):
    """Gemini 用 LangChain ChatModel を返す。"""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        raise RuntimeError(
            "langchain-google-genai is required for provider 'gemini'. "
            "Install with: pip install -U langchain-google-genai"
        )

    api_key = config.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("Environment variable GEMINI_API_KEY is not set")

    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=0,
    )


def create_ollama_llm(
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 512,
    *,
    reasoning: str | bool | None = None,
):
    """Ollama 用 LangChain ChatModel を返す。"""
    try:
        from langchain_ollama import ChatOllama
    except ImportError:
        raise RuntimeError(
            "langchain-ollama is required for provider 'ollama'. "
            "Install with: pip install -U langchain-ollama"
        )

    options: dict[str, Any] = {}
    if reasoning is not None:
        cleaned = reasoning.strip() if isinstance(reasoning, str) else reasoning
        if cleaned:
            options["reasoning"] = cleaned

    return ChatOllama(
        model=model,
        temperature=temperature,
        num_predict=max_tokens,
        validate_model_on_init=True,
        **options,
    )


# --- Local llama-cpp-python support ---


def _find_model_file_in_dir(dir_path: Path | None) -> Path | None:
    """
    指定ディレクトリからローカルモデルファイルを探して最初に見つかったもののパスを返す。
    サポートする拡張子: .gguf, .ggml, .bin, .safetensors, .pth, .pt
    """
    if not dir_path or not dir_path.exists():
        return None
    exts = ("*.gguf", "*.ggml", "*.bin", "*.safetensors", "*.pth", "*.pt")
    for ext in exts:
        for p in dir_path.glob(ext):
            if p.is_file():
                return p
    # no match
    return None


def create_local_llama_llm(
    model: str | None, temperature: float = 0.7, max_tokens: int = 512
):
    """llama-cpp-python を LangChain 経由で呼び出す。"""
    try:
        from langchain_community.llms import LlamaCpp
    except ImportError:
        raise RuntimeError(
            "langchain-community and llama-cpp-python are required for provider 'local'. "
            "Install with: pip install -U langchain-community llama-cpp-python"
        )

    model_path: Path | None = None
    if model:
        p = Path(model)
        if p.is_dir():
            model_path = _find_model_file_in_dir(p)
        else:
            model_path = p
    else:
        model_path = _find_model_file_in_dir(config.LOCAL_MODEL_DIR)

    if not model_path or not model_path.exists():
        raise RuntimeError(
            f"Local model not found. Provided model: {model}. "
            f"Searched default dir: {config.LOCAL_MODEL_DIR}"
        )

    n_threads = min(4, os.cpu_count() or 1)

    return LlamaCpp(
        model_path=str(model_path),
        temperature=temperature,
        max_tokens=max_tokens,
        n_ctx=2048,
        n_threads=n_threads,
        verbose=False,
    )
