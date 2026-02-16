"""Tests for LM Studio provider."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from providers.base import ProviderConfig
from providers.lmstudio import LMStudioProvider
from config.nim import NimSettings


class MockMessage:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class MockRequest:
    def __init__(self, **kwargs):
        self.model = "lmstudio-community/qwen2.5-7b-instruct"
        self.messages = [MockMessage("user", "Hello")]
        self.max_tokens = 100
        self.temperature = 0.5
        self.top_p = 0.9
        self.system = "System prompt"
        self.stop_sequences = None
        self.tools = []
        self.extra_body = {}
        self.thinking = MagicMock()
        self.thinking.enabled = True
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def lmstudio_config():
    return ProviderConfig(
        api_key="lm-studio",
        base_url="http://localhost:1234/v1",
        rate_limit=10,
        rate_window=60,
        nim_settings=NimSettings(),
    )


@pytest.fixture(autouse=True)
def mock_rate_limiter():
    """Mock the global rate limiter to prevent waiting."""
    with patch("providers.lmstudio.client.GlobalRateLimiter") as mock:
        instance = mock.get_instance.return_value
        instance.wait_if_blocked = AsyncMock(return_value=False)

        async def _passthrough(fn, *args, **kwargs):
            return await fn(*args, **kwargs)

        instance.execute_with_retry = AsyncMock(side_effect=_passthrough)
        yield instance


@pytest.fixture
def lmstudio_provider(lmstudio_config):
    return LMStudioProvider(lmstudio_config)


def test_init(lmstudio_config):
    """Test provider initialization."""
    with patch("providers.lmstudio.client.AsyncOpenAI") as mock_openai:
        provider = LMStudioProvider(lmstudio_config)
        assert provider._api_key == "lm-studio"
        assert provider._base_url == "http://localhost:1234/v1"
        mock_openai.assert_called_once()


def test_init_with_empty_api_key():
    """Provider uses lm-studio placeholder when api_key is empty."""
    config = ProviderConfig(
        api_key="",
        base_url="http://localhost:1234/v1",
        rate_limit=10,
        rate_window=60,
        nim_settings=NimSettings(),
    )
    with patch("providers.lmstudio.client.AsyncOpenAI") as mock_openai:
        provider = LMStudioProvider(config)
        assert provider._api_key == "lm-studio"


def test_build_request_body_no_extra_body(lmstudio_provider):
    """LM Studio request body does NOT include extra_body/reasoning."""
    req = MockRequest()
    body = lmstudio_provider._build_request_body(req)

    assert body["model"] == "lmstudio-community/qwen2.5-7b-instruct"
    assert body["temperature"] == 0.5
    assert len(body["messages"]) == 2  # System + User
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"] == "System prompt"

    assert "extra_body" not in body


def test_build_request_body_base_url_and_model(lmstudio_provider):
    """Base URL and model are correct in provider config."""
    assert lmstudio_provider._base_url == "http://localhost:1234/v1"
    req = MockRequest(model="lmstudio-community/qwen2.5-7b-instruct")
    body = lmstudio_provider._build_request_body(req)
    assert body["model"] == "lmstudio-community/qwen2.5-7b-instruct"


@pytest.mark.asyncio
async def test_stream_response_text(lmstudio_provider):
    """Test streaming text response."""
    req = MockRequest()

    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [
        MagicMock(
            delta=MagicMock(content="Hello", reasoning_content=None),
            finish_reason=None,
        )
    ]
    mock_chunk1.usage = None

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [
        MagicMock(
            delta=MagicMock(content=" World", reasoning_content=None),
            finish_reason="stop",
        )
    ]
    mock_chunk2.usage = MagicMock(completion_tokens=10)

    async def mock_stream():
        yield mock_chunk1
        yield mock_chunk2

    with patch.object(
        lmstudio_provider._client.chat.completions, "create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = mock_stream()

        events = []
        async for event in lmstudio_provider.stream_response(req):
            events.append(event)

        assert len(events) > 0
        assert "event: message_start" in events[0]

        text_content = ""
        for e in events:
            if "event: content_block_delta" in e and '"text_delta"' in e:
                for line in e.splitlines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        if "delta" in data and "text" in data["delta"]:
                            text_content += data["delta"]["text"]

        assert "Hello World" in text_content


@pytest.mark.asyncio
async def test_stream_response_reasoning_content(lmstudio_provider):
    """Test streaming with reasoning_content delta (if LM Studio adds support)."""
    req = MockRequest()

    mock_chunk = MagicMock()
    mock_chunk.choices = [
        MagicMock(
            delta=MagicMock(content=None, reasoning_content="Thinking..."),
            finish_reason=None,
        )
    ]
    mock_chunk.usage = None

    async def mock_stream():
        yield mock_chunk

    with patch.object(
        lmstudio_provider._client.chat.completions, "create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = mock_stream()

        events = []
        async for event in lmstudio_provider.stream_response(req):
            events.append(event)

        found_thinking = False
        for e in events:
            if "event: content_block_delta" in e and '"thinking_delta"' in e:
                if "Thinking..." in e:
                    found_thinking = True
        assert found_thinking
