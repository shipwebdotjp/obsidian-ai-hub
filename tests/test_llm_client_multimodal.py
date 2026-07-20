from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from obsidian_ai_hub.utils import llm_client


@pytest.fixture
def temp_image(tmp_path):
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake image data")
    return img_path


def test_generate_llm_response_text_only():
    with patch("obsidian_ai_hub.utils.llm_client.create_langchain_llm") as mock_create:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="Hello world")
        mock_create.return_value = mock_llm

        response = llm_client.generate_llm_response(
            provider="openai", model="gpt-4", prompt="Hi"
        )

        assert response == "Hello world"
        # Verify HumanMessage content is just a string
        args, _ = mock_llm.invoke.call_args
        messages = args[0]
        assert len(messages) == 1
        assert isinstance(messages[0], HumanMessage)
        assert messages[0].content == "Hi"


def test_generate_llm_response_openai_multimodal(temp_image):
    with patch("obsidian_ai_hub.utils.llm_client.create_langchain_llm") as mock_create:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="I see an image")
        mock_create.return_value = mock_llm

        response = llm_client.generate_llm_response(
            provider="openai",
            model="gpt-4-vision",
            prompt="What is this?",
            files=[temp_image],
        )

        assert response == "I see an image"
        args, _ = mock_llm.invoke.call_args
        messages = args[0]
        assert len(messages) == 1
        content = messages[0].content
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "What is this?"}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_generate_llm_response_ollama_multimodal(temp_image):
    with patch("obsidian_ai_hub.utils.llm_client.create_langchain_llm") as mock_create:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="Ollama sees it")
        mock_create.return_value = mock_llm

        response = llm_client.generate_llm_response(
            provider="ollama", model="llava", prompt="Describe", files=[temp_image]
        )

        assert response == "Ollama sees it"
        args, _ = mock_llm.invoke.call_args
        messages = args[0]
        assert len(messages) == 1
        content = messages[0].content
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "Describe"}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_generate_llm_response_file_not_found():
    with pytest.raises(FileNotFoundError):
        llm_client.generate_llm_response(
            provider="openai", model="gpt-4", prompt="Hi", files=["non_existent.jpg"]
        )


def test_generate_llm_response_local_multimodal_warning(temp_image, caplog):
    with patch("obsidian_ai_hub.utils.llm_client.create_langchain_llm") as mock_create:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="Local response")
        mock_create.return_value = mock_llm

        response = llm_client.generate_llm_response(
            provider="local", model="some-model", prompt="Hi", files=[temp_image]
        )

        assert response == "Local response"
        assert "Multimodal is not supported for provider 'local'" in caplog.text
        args, _ = mock_llm.invoke.call_args
        messages = args[0]
        assert messages[0].content == "Hi"
        assert not hasattr(messages[0], "images") or not messages[0].images
