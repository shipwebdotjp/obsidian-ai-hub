import json
import os
import time
from pathlib import Path
from typing import Any, Sequence
import logging

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


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


def _with_exponential_backoff(func, *, max_attempts: int = 3, initial_delay: float = 1.0):
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


def _content_to_text(content: Any) -> str:
    """
    LangChain の AIMessage.content は str のこともあれば、
    provider によって list[dict] 形式になることもあるため、文字列化する。
    """
    if content is None:
        return ""

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "".join(parts).strip()

    return str(content).strip()


def generate_llm_response(
    provider: str,
    model: str,
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 512,
) -> str:
    """
    指定のモデルとプロンプトで OpenAI/Gemini/Local/Ollama を呼び出し、
    生成されたテキストを返す。

    既存コードとの互換性のため、戻り値は str のままにしている。
    """
    llm = create_langchain_llm(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    def _call() -> str:
        message = llm.invoke([HumanMessage(content=prompt)])
        return _content_to_text(message.content)

    return _with_exponential_backoff(_call)


def generate_llm_response_with_tools(
    provider: str,
    model: str,
    prompt: str,
    tools: Sequence[BaseTool],
    temperature: float = 0.7,
    max_tokens: int = 512,
    max_iterations: int = 10,
) -> str:
    """
    ツール呼び出しをサポートしたLLMレスポンス生成。
    LLMがツール呼び出しを要求する限りループし、最終的なテキスト回答を返す。
    """
    llm = create_langchain_llm(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    llm_with_tools = llm.bind_tools(list(tools))
    tools_by_name = {tool.name: tool for tool in tools}

    messages = [HumanMessage(content=prompt)]

    iterations = 0
    while iterations < max_iterations:
        iterations += 1
        def _call():
            return llm_with_tools.invoke(messages)

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
            logger.debug(f"Tool called: {tool_name} with args {tool_call['args']} returned result: {result}")
            messages.append(
                ToolMessage(
                    content=json.dumps({"result": result}, ensure_ascii=False),
                    tool_call_id=tool_call["id"],
                )
            )

    # If we reached max_iterations and the last message still requested tool calls,
    # we need one final LLM call without tool binding to get a summary response.
    def _final_call():
        return llm.invoke(messages)

    final_ai_msg = _with_exponential_backoff(_final_call)
    return _content_to_text(final_ai_msg.content)


def create_langchain_llm(
    provider: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 512,
):
    """
    provider 名から LangChain の ChatModel / LLM を生成する。

    - openai: ChatOpenAI
    - gemini: ChatGoogleGenerativeAI
    - ollama: ChatOllama
    - local: LlamaCpp
    """
    if provider == "openai":
        return create_openai_llm(model, temperature, max_tokens)

    if provider == "gemini":
        return create_gemini_llm(model, temperature, max_tokens)

    if provider == "ollama":
        return create_ollama_llm(model, temperature, max_tokens)

    if provider == "local":
        return create_local_llama_llm(model, temperature, max_tokens)

    raise ValueError(f"Unknown provider: {provider}")


def create_openai_llm(model: str, temperature: float = 0.7, max_tokens: int = 512):
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

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=0,  # 外側の _with_exponential_backoff に任せる
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


def create_ollama_llm(model: str, temperature: float = 0.7, max_tokens: int = 512):
    """Ollama 用 LangChain ChatModel を返す。"""
    try:
        from langchain_ollama import ChatOllama
    except ImportError:
        raise RuntimeError(
            "langchain-ollama is required for provider 'ollama'. "
            "Install with: pip install -U langchain-ollama"
        )

    return ChatOllama(
        model=model,
        temperature=temperature,
        num_predict=max_tokens,
        validate_model_on_init=True,
    )


# --- Local llama-cpp-python support ---

def _find_model_file_in_dir(dir_path: Path) -> Path | None:
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


def create_local_llama_llm(model: str | None, temperature: float = 0.7, max_tokens: int = 512):
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
