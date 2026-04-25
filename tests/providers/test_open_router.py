"""Tests for the OpenRouter provider."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from providers.base import ProviderConfig
from providers.open_router import OpenRouterProvider
from providers.open_router.request import OPENROUTER_DEFAULT_MAX_TOKENS


class MockMessage:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class MockTool:
    def __init__(self):
        self.name = "run_command"
        self.description = "Run a command"
        self.input_schema = {
            "type": "object",
            "properties": {"cmd": {"type": "string"}},
        }


class MockRequest:
    def __init__(self, **kwargs):
        self.model = "stepfun/step-3.5-flash:free"
        self.messages = [MockMessage("user", "Hello")]
        self.max_tokens = 100
        self.temperature = 0.5
        self.top_p = 0.9
        self.top_k = 20
        self.system = "System prompt"
        self.stop_sequences = ["STOP"]
        self.stream = False
        self.metadata = {"source": "request"}
        self.tools = [MockTool()]
        self.tool_choice = {"type": "auto"}
        self.extra_body = {}
        self.original_model = "claude-sonnet-4-20250514"
        self.resolved_provider_model = "open_router/stepfun/step-3.5-flash:free"
        self.thinking = MagicMock()
        self.thinking.enabled = True
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeResponse:
    """Simple async streaming response for provider tests."""

    def __init__(self, *, status_code=200, lines=None, text=""):
        self.status_code = status_code
        self._lines = lines or []
        self._text = text
        self.is_closed = False
        self.request = httpx.Request("POST", "https://openrouter.ai/api/v1/messages")

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    def raise_for_status(self):
        response = httpx.Response(
            self.status_code,
            request=self.request,
            text=self._text,
        )
        response.raise_for_status()

    async def aclose(self):
        self.is_closed = True


def parse_sse_event(event: str) -> tuple[str | None, dict]:
    """Parse an SSE event string into event type and JSON payload."""
    event_type = None
    data_lines: list[str] = []
    for line in event.strip().splitlines():
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    return event_type, json.loads("\n".join(data_lines))


@pytest.fixture
def open_router_config():
    return ProviderConfig(
        api_key="test_openrouter_key",
        base_url="https://openrouter.ai/api/v1",
        rate_limit=10,
        rate_window=60,
    )


@pytest.fixture(autouse=True)
def mock_rate_limiter():
    """Mock the global rate limiter to prevent waiting."""

    @asynccontextmanager
    async def _slot():
        yield

    with patch("providers.anthropic_compat.GlobalRateLimiter") as mock:
        instance = mock.get_instance.return_value

        async def _passthrough(fn, *args, **kwargs):
            return await fn(*args, **kwargs)

        instance.execute_with_retry = AsyncMock(side_effect=_passthrough)
        instance.wait_if_blocked = AsyncMock(return_value=False)
        instance.concurrency_slot.side_effect = _slot
        yield instance


@pytest.fixture
def open_router_provider(open_router_config):
    return OpenRouterProvider(open_router_config)


def test_init_uses_httpx_client_with_proxy_and_timeouts():
    """Provider initialization configures an httpx client directly."""
    config = ProviderConfig(
        api_key="test_openrouter_key",
        base_url="https://openrouter.ai/api/v1",
        proxy="socks5://127.0.0.1:9999",
        http_read_timeout=600.0,
        http_write_timeout=15.0,
        http_connect_timeout=5.0,
    )

    with patch("httpx.AsyncClient") as mock_client:
        provider = OpenRouterProvider(config)

    assert provider._api_key == "test_openrouter_key"
    assert provider._base_url == "https://openrouter.ai/api/v1"
    kwargs = mock_client.call_args.kwargs
    timeout = kwargs["timeout"]
    assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert kwargs["proxy"] == "socks5://127.0.0.1:9999"
    assert timeout.read == 600.0
    assert timeout.write == 15.0
    assert timeout.connect == 5.0


def test_build_request_body_is_anthropic_shaped(open_router_provider):
    """System stays top-level and internal fields are stripped."""
    req = MockRequest()

    body = open_router_provider._build_request_body(req)

    assert body["model"] == "stepfun/step-3.5-flash:free"
    assert body["system"] == "System prompt"
    assert body["stream"] is True
    assert body["temperature"] == 0.5
    assert body["top_p"] == 0.9
    assert body["top_k"] == 20
    assert body["stop_sequences"] == ["STOP"]
    assert body["metadata"] == {"source": "request"}
    assert body["tool_choice"] == {"type": "auto"}
    assert len(body["messages"]) == 1
    assert body["messages"][0] == {"role": "user", "content": "Hello"}
    assert body["tools"][0]["name"] == "run_command"
    assert body["reasoning"] == {"enabled": True}
    assert "thinking" not in body
    assert "original_model" not in body
    assert "resolved_provider_model" not in body
    assert "extra_body" not in body


def test_build_request_body_extra_body_merges_top_level_and_preserves_overrides(
    open_router_provider,
):
    req = MockRequest(
        metadata={"source": "request"},
        extra_body={
            "metadata": {"source": "extra"},
            "reasoning": {"enabled": False},
            "service_tier": "flex",
            "stream": False,
        },
    )

    body = open_router_provider._build_request_body(req)

    assert body["metadata"] == {"source": "extra"}
    assert body["reasoning"] == {"enabled": False}
    assert body["service_tier"] == "flex"
    assert body["stream"] is True


def test_build_request_body_omits_reasoning_when_globally_disabled(open_router_config):
    provider = OpenRouterProvider(
        open_router_config.model_copy(update={"enable_thinking": False})
    )
    req = MockRequest()

    body = provider._build_request_body(req)

    assert "reasoning" not in body


def test_build_request_body_omits_reasoning_when_request_disables_thinking(
    open_router_provider,
):
    req = MockRequest()
    req.thinking.enabled = False

    body = open_router_provider._build_request_body(req)

    assert "reasoning" not in body


def test_build_request_body_default_max_tokens(open_router_provider):
    req = MockRequest(max_tokens=None)

    body = open_router_provider._build_request_body(req)

    assert body["max_tokens"] == OPENROUTER_DEFAULT_MAX_TOKENS


@pytest.mark.asyncio
async def test_stream_response_passthroughs_anthropic_sse(open_router_provider):
    req = MockRequest()
    request_obj = httpx.Request("POST", "https://openrouter.ai/api/v1/messages")
    response = FakeResponse(
        lines=[
            "event: message_start",
            'data: {"type":"message_start","message":{"id":"msg_1","type":"message","role":"assistant","content":[],"model":"stepfun/step-3.5-flash:free","stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":0,"output_tokens":0}}}',
            "",
            "event: content_block_start",
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
            "",
            "event: content_block_delta",
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}',
            "",
            "event: content_block_stop",
            'data: {"type":"content_block_stop","index":0}',
            "",
            "event: message_delta",
            'data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"input_tokens":22,"output_tokens":1}}',
            "",
            "event: message_stop",
            'data: {"type":"message_stop"}',
            "",
        ]
    )

    with (
        patch.object(
            open_router_provider._client,
            "build_request",
            return_value=request_obj,
        ) as mock_build_request,
        patch.object(
            open_router_provider._client,
            "send",
            new_callable=AsyncMock,
            return_value=response,
        ) as mock_send,
    ):
        events = [e async for e in open_router_provider.stream_response(req)]

    assert events[0].startswith("event: message_start")
    assert any("Hello" in event for event in events)
    assert any("event: message_stop" in event for event in events)
    assert mock_build_request.call_args.args[:2] == ("POST", "/messages")
    assert (
        mock_build_request.call_args.kwargs["headers"]["anthropic-version"]
        == "2023-06-01"
    )
    assert mock_build_request.call_args.kwargs["headers"]["Authorization"].startswith(
        "Bearer "
    )
    mock_send.assert_awaited_once_with(request_obj, stream=True)


@pytest.mark.asyncio
async def test_stream_response_filters_thinking_when_disabled(open_router_config):
    provider = OpenRouterProvider(
        open_router_config.model_copy(update={"enable_thinking": False})
    )
    req = MockRequest()
    request_obj = httpx.Request("POST", "https://openrouter.ai/api/v1/messages")
    response = FakeResponse(
        lines=[
            "event: message_start",
            'data: {"type":"message_start","message":{"id":"msg_1","type":"message","role":"assistant","content":[],"model":"stepfun/step-3.5-flash:free","stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":0,"output_tokens":0}}}',
            "",
            "event: content_block_start",
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}',
            "",
            "event: content_block_delta",
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"secret"}}',
            "",
            "event: content_block_stop",
            'data: {"type":"content_block_stop","index":0}',
            "",
            "event: content_block_start",
            'data: {"type":"content_block_start","index":1,"content_block":{"type":"text","text":""}}',
            "",
            "event: content_block_delta",
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"Visible"}}',
            "",
            "event: content_block_stop",
            'data: {"type":"content_block_stop","index":1}',
            "",
            "event: message_delta",
            'data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"input_tokens":22,"output_tokens":1}}',
            "",
            "event: message_stop",
            'data: {"type":"message_stop"}',
            "",
        ]
    )

    with (
        patch.object(provider._client, "build_request", return_value=request_obj),
        patch.object(
            provider._client,
            "send",
            new_callable=AsyncMock,
            return_value=response,
        ),
    ):
        events = [e async for e in provider.stream_response(req)]

    event_text = "".join(events)
    assert "thinking_delta" not in event_text
    assert "secret" not in event_text
    assert "Visible" in event_text

    content_block_starts = [
        parse_sse_event(event)
        for event in events
        if event.startswith("event: content_block_start")
    ]
    assert len(content_block_starts) == 1
    _, payload = content_block_starts[0]
    assert payload["content_block"]["type"] == "text"
    assert payload["index"] == 0


@pytest.mark.asyncio
async def test_stream_response_error_path_emits_existing_sse_shape(
    open_router_provider,
):
    req = MockRequest()
    request_obj = httpx.Request("POST", "https://openrouter.ai/api/v1/messages")
    response = FakeResponse(status_code=400, text='{"error":"bad request"}')

    with (
        patch.object(
            open_router_provider._client,
            "build_request",
            return_value=request_obj,
        ),
        patch.object(
            open_router_provider._client,
            "send",
            new_callable=AsyncMock,
            return_value=response,
        ),
    ):
        events = [
            event
            async for event in open_router_provider.stream_response(
                req,
                input_tokens=12,
                request_id="req_123",
            )
        ]

    assert events[0].startswith("event: message_start")
    assert any("400 Bad Request" in event for event in events)
    assert any("(request_id=req_123)" in event for event in events)
    assert any("event: message_delta" in event for event in events)
    assert any("event: message_stop" in event for event in events)
