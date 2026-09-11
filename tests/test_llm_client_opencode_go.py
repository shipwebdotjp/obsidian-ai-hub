import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage
from obsidian_ai_hub.utils import llm_client


def test_opencode_go_openai_compatible_routing():
    """Verify that OpenAI-compatible model IDs correctly route to ChatOpenAI with proper arguments."""
    with (
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_API_KEY",
            "test_opencode_key",
        ),
        patch("langchain_openai.ChatOpenAI") as mock_chat_openai,
    ):
        mock_instance = MagicMock()
        mock_chat_openai.return_value = mock_instance

        # List of models starting with glm-, kimi-, deepseek-, mimo-
        models = ["glm-4", "kimi-latest", "deepseek-v3", "mimo-small"]
        for m in models:
            llm = llm_client.create_langchain_llm(
                provider="opencode_go", model=m, temperature=0.5, max_tokens=256
            )
            assert llm == mock_instance
            mock_chat_openai.assert_called_with(
                model=m,
                api_key="test_opencode_key",
                base_url="https://opencode.ai/zen/go/v1",
                temperature=0.5,
                max_tokens=256,
                max_retries=0,
                default_headers={
                    "User-Agent": "obsidian-ai-hub/1.0",
                    "x-opencode-session": "obsidian-ai-hub",
                },
            )


def test_opencode_go_gpt_models_use_responses_api():
    with (
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_API_KEY",
            "test_opencode_key",
        ),
        patch("langchain_openai.ChatOpenAI") as mock_chat_openai,
    ):
        llm_client.create_langchain_llm(
            provider="opencode_go",
            model="gpt-5.6-terra",
            temperature=0.5,
            max_tokens=256,
        )

    mock_chat_openai.assert_called_once_with(
        model="gpt-5.6-terra",
        api_key="test_opencode_key",
        base_url="https://opencode.ai/zen/go/v1",
        temperature=0.5,
        max_tokens=256,
        max_retries=0,
        use_responses_api=True,
        default_headers={
            "User-Agent": "obsidian-ai-hub/1.0",
            "x-opencode-session": "obsidian-ai-hub",
        },
    )


def test_opencode_go_anthropic_compatible_routing():
    """Verify that Anthropic-compatible model IDs correctly route to ChatAnthropic with proper arguments."""
    with (
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_API_KEY",
            "test_opencode_key",
        ),
        patch("langchain_anthropic.ChatAnthropic") as mock_chat_anthropic,
    ):
        mock_instance = MagicMock()
        mock_chat_anthropic.return_value = mock_instance

        # List of models starting with minimax-, qwen3.7-, qwen3.6-
        models = ["minimax-v1", "qwen3.7-72b", "qwen3.6-coder"]
        for m in models:
            llm = llm_client.create_langchain_llm(
                provider="opencode_go", model=m, temperature=0.4, max_tokens=100
            )
            assert llm == mock_instance
            mock_chat_anthropic.assert_called_with(
                model=m,
                anthropic_api_key="test_opencode_key",
                base_url="https://opencode.ai/zen/go/v1",
                temperature=0.4,
                max_tokens=100,
                max_retries=0,
                default_headers={
                    "User-Agent": "obsidian-ai-hub/1.0",
                    "x-opencode-session": "obsidian-ai-hub",
                },
            )


def test_opencode_go_missing_api_key():
    """Verify that missing OPENCODE_API_KEY raises a RuntimeError."""
    with (
        patch("obsidian_ai_hub.utils.llm_client.config.OPENCODE_API_KEY", None),
        patch("langchain_openai.ChatOpenAI") as mock_chat_openai,
        patch("langchain_anthropic.ChatAnthropic") as mock_chat_anthropic,
    ):
        with pytest.raises(RuntimeError) as exc_info:
            llm_client.create_langchain_llm(provider="opencode_go", model="deepseek-v3")
        assert "Environment variable OPENCODE_API_KEY is not set" in str(exc_info.value)
        mock_chat_openai.assert_not_called()
        mock_chat_anthropic.assert_not_called()


def test_opencode_go_unsupported_model_id():
    """Verify that an unsupported model ID raises a RuntimeError."""
    with (
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_API_KEY",
            "test_opencode_key",
        ),
        patch("langchain_openai.ChatOpenAI") as mock_chat_openai,
        patch("langchain_anthropic.ChatAnthropic") as mock_chat_anthropic,
    ):
        with pytest.raises(RuntimeError) as exc_info:
            llm_client.create_langchain_llm(
                provider="opencode_go", model="unsupported-model-v1"
            )
        assert "Unsupported model ID for opencode_go: unsupported-model-v1" in str(
            exc_info.value
        )
        mock_chat_openai.assert_not_called()
        mock_chat_anthropic.assert_not_called()


def test_generate_llm_response_opencode_go_integration():
    """Verify integration flow using generate_llm_response with opencode_go provider."""
    with (
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_API_KEY",
            "test_opencode_key",
        ),
        patch("langchain_openai.ChatOpenAI") as mock_chat_openai,
    ):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(
            content="Generated response from OpenCode Go"
        )
        mock_chat_openai.return_value = mock_llm

        response = llm_client.generate_llm_response(
            provider="opencode_go",
            model="deepseek-v3",
            prompt="Tell me about OpenCode Go.",
        )

        assert response == "Generated response from OpenCode Go"
        mock_llm.invoke.assert_called_once()


def test_generate_llm_response_with_tools_uses_responses_api_for_openai():
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value.invoke.return_value = AIMessage(
        content="Research complete"
    )

    with patch(
        "obsidian_ai_hub.utils.llm_client.create_langchain_llm", return_value=mock_llm
    ) as factory:
        response = llm_client.generate_llm_response_with_tools(
            provider="openai",
            model="gpt-5.6-terra",
            prompt="Research this topic",
            tools=[],
        )

    assert response == "Research complete"
    factory.assert_called_once_with(
        provider="openai",
        model="gpt-5.6-terra",
        temperature=0.7,
        max_tokens=16384,
        use_responses_api=True,
        store=False,
    )


def test_generate_llm_response_with_tools_keeps_non_openai_default():
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value.invoke.return_value = AIMessage(
        content="Research complete"
    )

    with patch(
        "obsidian_ai_hub.utils.llm_client.create_langchain_llm", return_value=mock_llm
    ) as factory:
        response = llm_client.generate_llm_response_with_tools(
            provider="opencode_go",
            model="deepseek-v3",
            prompt="Research this topic",
            tools=[],
        )

    assert response == "Research complete"
    factory.assert_called_once_with(
        provider="opencode_go",
        model="deepseek-v3",
        temperature=0.7,
        max_tokens=16384,
    )


def test_opencode_go_sends_session_header_without_network():
    """ChatOpenAI に User-Agent と x-opencode-session が default_headers で渡される。"""
    with (
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_API_KEY",
            "test_opencode_key",
        ),
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_SESSION_ID",
            "obsidian-ai-hub",
        ),
        patch("langchain_openai.ChatOpenAI") as mock_chat_openai,
    ):
        llm_client.create_opencode_go_llm(model="deepseek-v3")

    _, kwargs = mock_chat_openai.call_args
    assert kwargs["default_headers"] == {
        "User-Agent": "obsidian-ai-hub/1.0",
        "x-opencode-session": "obsidian-ai-hub",
    }
    mock_chat_openai.assert_called_once()


def test_opencode_go_merges_existing_default_headers():
    """呼び出し側の既存 default_headers を消さずにマージし、User-Agent は固定値で上書きする。"""
    with (
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_API_KEY",
            "test_opencode_key",
        ),
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_SESSION_ID",
            "obsidian-ai-hub",
        ),
        patch("langchain_openai.ChatOpenAI") as mock_chat_openai,
    ):
        llm_client.create_opencode_go_llm(
            model="deepseek-v3",
            default_headers={"x-custom": "keep-me", "User-Agent": "custom-agent/2.0"},
        )

    _, kwargs = mock_chat_openai.call_args
    assert kwargs["default_headers"] == {
        "x-custom": "keep-me",
        "User-Agent": "obsidian-ai-hub/1.0",
        "x-opencode-session": "obsidian-ai-hub",
    }


def test_opencode_go_session_id_explicit_priority():
    """明示的な session_id が呼び出し側ヘッダーや config より優先される。"""
    with (
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_API_KEY",
            "test_opencode_key",
        ),
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_SESSION_ID",
            "config-session",
        ),
        patch("langchain_openai.ChatOpenAI") as mock_chat_openai,
    ):
        llm_client.create_opencode_go_llm(
            model="gpt-5.6-terra",
            session_id="asess_explicit123",
            default_headers={"x-opencode-session": "header-session"},
        )

    _, kwargs = mock_chat_openai.call_args
    assert kwargs["default_headers"]["x-opencode-session"] == "asess_explicit123"
    assert kwargs["default_headers"]["User-Agent"] == "obsidian-ai-hub/1.0"


def test_opencode_go_empty_session_id_fallback():
    """空の session_id（None や ""）は呼び出し側ヘッダー → config → 固定フォールバックへ戻る。"""
    with (
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_API_KEY",
            "test_opencode_key",
        ),
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_SESSION_ID",
            "config-session",
        ),
        patch("langchain_openai.ChatOpenAI") as mock_chat_openai,
    ):
        # 1. session_id="" with caller header -> uses caller header
        llm_client.create_opencode_go_llm(
            model="gpt-5.6-terra",
            session_id="",
            default_headers={"x-opencode-session": "header-session"},
        )
        _, kwargs = mock_chat_openai.call_args
        assert kwargs["default_headers"]["x-opencode-session"] == "header-session"

        # 2. session_id=None without caller header -> uses config
        llm_client.create_opencode_go_llm(
            model="gpt-5.6-terra",
            session_id=None,
        )
        _, kwargs = mock_chat_openai.call_args
        assert kwargs["default_headers"]["x-opencode-session"] == "config-session"


def test_non_opencode_go_providers_no_added_headers():
    """opencode_go 以外のプロバイダー（openai など）にはヘッダーが追加されない。"""
    with (
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENAI_API_KEY",
            "test_openai_key",
        ),
        patch("langchain_openai.ChatOpenAI") as mock_chat_openai,
    ):
        llm_client.create_langchain_llm(
            provider="openai",
            model="gpt-5.6-terra",
            session_id="asess_should_not_be_passed",
        )

    _, kwargs = mock_chat_openai.call_args
    assert "default_headers" not in kwargs or kwargs["default_headers"] is None


def test_opencode_go_session_header_contains_no_secrets():
    """ヘッダー値に APIキー・プロンプト・個人情報を含めない。"""
    secret_key = "test_opencode_key_secret"
    prompt = "user prompt with PII alice@example.com"
    with (
        patch(
            "obsidian_ai_hub.utils.llm_client.config.OPENCODE_API_KEY",
            secret_key,
        ),
        patch("langchain_openai.ChatOpenAI") as mock_chat_openai,
    ):
        llm_client.create_opencode_go_llm(model="deepseek-v3")

    _, kwargs = mock_chat_openai.call_args
    session_value = kwargs["default_headers"]["x-opencode-session"]
    assert secret_key not in session_value
    assert prompt not in session_value
    assert session_value == "obsidian-ai-hub"


@pytest.mark.anyio
async def test_agent_runtime_passes_session_id_to_llm():
    """Verify generate_agent_stream passes session_id to create_langchain_llm."""
    from langchain_core.messages import AIMessageChunk
    from obsidian_ai_hub.agents import runtime as agent_runtime

    mock_llm = MagicMock()
    mock_chunk = AIMessageChunk(content="Hello from agent")

    async def mock_astream(*args, **kwargs):
        yield mock_chunk

    mock_llm.astream = mock_astream

    agent = {
        "agent_id": "ag_1",
        "name": "TestAgent",
        "provider": "opencode_go",
        "model": "deepseek-v3",
        "tool_ids": [],
    }
    session = {"session_id": "asess_test123", "agent_id": "ag_1"}
    run = {"run_id": "arun_test123", "user_message_id": "umsg_123"}

    with (
        patch(
            "obsidian_ai_hub.agents.runtime.create_langchain_llm",
            return_value=mock_llm,
        ) as mock_create_llm,
        patch("obsidian_ai_hub.agents.store.complete_run", return_value=({}, {})),
        patch("obsidian_ai_hub.agents.store.list_messages", return_value=[]),
    ):
        events = []
        async for evt in agent_runtime.generate_agent_stream(
            agent=agent,
            session=session,
            run=run,
            history_messages=[],
            user_content="Hello agent",
        ):
            events.append(evt)

        mock_create_llm.assert_called()
        _, kwargs = mock_create_llm.call_args
        assert kwargs.get("session_id") == "asess_test123"


def test_subagent_delegation_passes_parent_session_id_to_llm():
    """Verify execute_subagent_core passes parent session_id from trusted_ctx to create_langchain_llm."""
    from obsidian_ai_hub.agents import runtime as agent_runtime

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(content="Subagent response")

    agent = {
        "agent_id": "ag_child",
        "name": "ChildAgent",
        "provider": "opencode_go",
        "model": "deepseek-v3",
        "tool_ids": [],
    }
    trusted_ctx = {
        "session_id": "asess_parent123",
        "run_id": "arun_parent123",
    }

    with patch(
        "obsidian_ai_hub.agents.runtime.create_langchain_llm",
        return_value=mock_llm,
    ) as mock_create_llm:
        res = agent_runtime.execute_subagent_core(
            agent=agent,
            task="Do subtask",
            trusted_ctx=trusted_ctx,
            depth=1,
        )
        assert res["status"] == "succeeded"

        mock_create_llm.assert_called()
        _, kwargs = mock_create_llm.call_args
        assert kwargs.get("session_id") == "asess_parent123"


@pytest.mark.anyio
async def test_coding_orchestrator_passes_session_id_to_llm():
    """Verify CodingOrchestrator.generate_response_events passes session_id to create_langchain_llm."""
    from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator

    mock_llm = MagicMock()

    async def mock_ainvoke(*args, **kwargs):
        return AIMessage(content="Orchestrator response")

    mock_llm.ainvoke.side_effect = mock_ainvoke
    mock_llm.bind_tools.return_value.ainvoke.side_effect = mock_ainvoke

    orchestrator = CodingOrchestrator(provider="opencode_go", model="deepseek-v3")

    with patch(
        "obsidian_ai_hub.coding.orchestrator.create_langchain_llm",
        return_value=mock_llm,
    ) as mock_create_llm:
        events = []
        async for evt in orchestrator.generate_response_events(
            history=[{"role": "user", "content": "Fix code"}],
            repo_path="/tmp/repo",
            backend_name="opencode",
            session_id="cses_test456",
        ):
            events.append(evt)

        mock_create_llm.assert_called()
        _, kwargs = mock_create_llm.call_args
        assert kwargs.get("session_id") == "cses_test456"
