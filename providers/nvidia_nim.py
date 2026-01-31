"""NVIDIA NIM provider - converts Anthropic format to OpenAI format for NIM."""

import logging
import os
import json
import uuid
from typing import Any, AsyncIterator

import httpx
from httpx import TimeoutException, ConnectTimeout

from .base import BaseProvider, ProviderConfig
from .utils import (
    SSEBuilder,
    map_stop_reason,
    ThinkTagParser,
    HeuristicToolParser,
    ContentType,
    extract_reasoning_from_delta,
)
from .exceptions import (
    APIError,
)
from .nvidia_mixins import (
    RequestBuilderMixin,
    StreamProcessorMixin,
    ErrorMapperMixin,
    ResponseConverterMixin,
)
from .rate_limit import GlobalRateLimiter

logger = logging.getLogger(__name__)


class NvidiaNimProvider(
    RequestBuilderMixin,
    StreamProcessorMixin,
    ErrorMapperMixin,
    ResponseConverterMixin,
    BaseProvider,
):
    """NVIDIA NIM provider using direct httpx requests."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._api_key = config.api_key or os.getenv("NVIDIA_NIM_API_KEY", "")
        self._base_url = (
            config.base_url
            or os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
        ).rstrip("/")
        self._nim_params = self._load_nim_params()
        self._global_rate_limiter = GlobalRateLimiter.get_instance()
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=30.0, read=120.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    async def stream_response(
        self, request: Any, input_tokens: int = 0
    ) -> AsyncIterator[str]:
        """Stream response in Anthropic SSE format."""
        # Wait if globally rate limited (proactive throttle + reactive block)
        waited_reactively = await self._global_rate_limiter.wait_if_blocked()

        if waited_reactively:
            # Yield error event for reactive rate limit blocking (user feedback)
            message_id = f"msg_{uuid.uuid4()}"
            sse = SSEBuilder(message_id, request.model, input_tokens)
            error_msg = "⏱️ Global rate limit active. Resuming now..."
            logger.info("NIM_STREAM: Reactive block detected, notified user")
            yield sse.message_start()
            for event in sse.emit_error(error_msg):
                yield event
            # After notification, we continue to the actual request

        body = self._build_request_body(request, stream=True)
        # Log compact request summary
        logger.info(
            f"NIM_STREAM: model={body.get('model')} msgs={len(body.get('messages', []))} tools={len(body.get('tools', []))}"
        )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        message_id = f"msg_{uuid.uuid4()}"
        sse = SSEBuilder(message_id, request.model, input_tokens)
        think_parser = ThinkTagParser()
        heuristic_parser = HeuristicToolParser()

        yield sse.message_start()

        finish_reason = None
        usage_info = None
        error_occurred = False
        error_message = ""

        try:
            async for chunk_json in self._stream_chunks(headers, body):
                # Process metadata
                if "usage" in chunk_json:
                    usage_info = chunk_json["usage"]

                if "choices" not in chunk_json or not chunk_json["choices"]:
                    continue

                choice = chunk_json["choices"][0]
                delta = choice.get("delta", {})

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                    logger.debug(f"NIM finish_reason: {finish_reason}")

                # Handle reasoning content from delta
                reasoning = extract_reasoning_from_delta(delta)
                if reasoning:
                    for event in sse.ensure_thinking_block():
                        yield event
                    yield sse.emit_thinking_delta(reasoning)

                # Handle text content with think tag and heuristic tool parsing
                if delta.get("content"):
                    for chunk in think_parser.feed(delta["content"]):
                        if chunk.type == ContentType.THINKING:
                            for event in sse.ensure_thinking_block():
                                yield event
                            yield sse.emit_thinking_delta(chunk.content)
                        else:
                            # Pass non-thinking text through heuristic tool parser
                            filtered_text, detected_tools = heuristic_parser.feed(
                                chunk.content
                            )

                            # Emit filtered text if any
                            if filtered_text:
                                for event in sse.ensure_text_block():
                                    yield event
                                yield sse.emit_text_delta(filtered_text)

                            # Emit detected heuristic tool calls
                            for tool_use in detected_tools:
                                for event in sse.close_content_blocks():
                                    yield event

                                block_idx = sse.blocks.allocate_index()
                                yield sse.content_block_start(
                                    block_idx,
                                    "tool_use",
                                    id=tool_use["id"],
                                    name=tool_use["name"],
                                )
                                yield sse.content_block_delta(
                                    block_idx,
                                    "input_json_delta",
                                    json.dumps(tool_use["input"]),
                                )
                                yield sse.content_block_stop(block_idx)

                # Handle native tool calls
                if delta.get("tool_calls"):
                    for event in sse.close_content_blocks():
                        yield event
                    for tc in delta["tool_calls"]:
                        for event in self._process_tool_call(tc, sse):
                            yield event

        except TimeoutException as e:
            timeout_type = "connect" if isinstance(e, ConnectTimeout) else "read"
            logger.error(f"NIM_TIMEOUT: type={timeout_type} model={body.get('model')}")
            error_occurred = True
            error_message = (
                f"⏱️ API Timeout ({timeout_type}): Request exceeded time limit"
            )
            logger.info("NIM_STREAM: Emitting SSE error event for timeout")
        except Exception as e:
            logger.error(f"NIM_ERROR: {type(e).__name__}: {e}")
            error_occurred = True
            error_message = str(e)
            logger.info("NIM_STREAM: Emitting SSE error event for exception")

        # Handle errors
        if error_occurred:
            for event in sse.emit_error(error_message):
                yield event
            logger.info("NIM_STREAM: Error event yielded, total events emitted")

        # Flush remaining content from parsers
        remaining = think_parser.flush()
        if remaining:
            if remaining.type == ContentType.THINKING:
                for event in sse.ensure_thinking_block():
                    yield event
                yield sse.emit_thinking_delta(remaining.content)
            else:
                for event in sse.ensure_text_block():
                    yield event
                yield sse.emit_text_delta(remaining.content)

        # Flush heuristic tool calls
        for tool_use in heuristic_parser.flush():
            for event in sse.close_content_blocks():
                yield event

            block_idx = sse.blocks.allocate_index()
            yield sse.content_block_start(
                block_idx,
                "tool_use",
                id=tool_use["id"],
                name=tool_use["name"],
            )
            yield sse.content_block_delta(
                block_idx,
                "input_json_delta",
                json.dumps(tool_use["input"]),
            )
            yield sse.content_block_stop(block_idx)

        # Ensure at least one text block exists to avoid "(no content)" in Claude Code
        # This handles cases where model only returns thinking or empty responses
        if (
            not error_occurred
            and sse.blocks.text_index == -1
            and not sse.blocks.tool_indices
        ):
            for event in sse.ensure_text_block():
                yield event
            yield sse.emit_text_delta(" ")  # Single space placeholder

        # Close all blocks
        for event in sse.close_all_blocks():
            yield event

        # Final events
        output_tokens = (
            usage_info.get("completion_tokens", 0)
            if usage_info
            else sse.estimate_output_tokens()
        )
        yield sse.message_delta(map_stop_reason(finish_reason), output_tokens)
        yield sse.message_stop()
        yield sse.done()

    async def _stream_chunks(self, headers: dict, body: dict):
        """Generator that yields parsed SSE data chunks from the API."""
        async with self._client.stream(
            "POST", f"{self._base_url}/chat/completions", headers=headers, json=body
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                raise self._map_error(
                    response_status=response.status_code,
                    error_text=error_text.decode("utf-8", errors="replace"),
                )

            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    event_end = buffer.index("\n\n")
                    event_data = buffer[:event_end]
                    buffer = buffer[event_end + 2 :]

                    parsed = self._parse_sse_event(event_data)
                    if parsed is not None:
                        yield parsed

            # Flush remaining non-empty buffer
            if buffer.strip():
                parsed = self._parse_sse_event(buffer)
                if parsed is not None:
                    yield parsed

    async def complete(self, request: Any) -> dict:
        """Make a non-streaming completion request."""
        # Wait if globally rate limited (proactive throttle + reactive block)
        await self._global_rate_limiter.wait_if_blocked()

        body = self._build_request_body(request, stream=False)
        # Log compact request summary
        logger.info(
            f"NIM_COMPLETE: model={body.get('model')} msgs={len(body.get('messages', []))} tools={len(body.get('tools', []))}"
        )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions", headers=headers, json=body
            )
        except TimeoutException as e:
            timeout_type = "connect" if isinstance(e, ConnectTimeout) else "read"
            logger.error(f"NIM_TIMEOUT: type={timeout_type} model={body.get('model')}")
            raise APIError(
                f"API Timeout ({timeout_type}): Request exceeded time limit",
                status_code=504,
            )

        if response.status_code != 200:
            raise self._map_error(
                response_status=response.status_code, error_text=response.text
            )
        return response.json()
