"""OpenRouter provider implementation."""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from providers.anthropic_compat import AnthropicMessagesProvider, StreamChunkMode
from providers.base import ProviderConfig
from providers.common import SSEBuilder, append_request_id

from .request import build_request_body

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class _SSEFilterState:
    """Track Anthropic content block index remapping while filtering thinking."""

    next_index: int = 0
    index_map: dict[int, int] = field(default_factory=dict)
    dropped_indexes: set[int] = field(default_factory=set)


class OpenRouterProvider(AnthropicMessagesProvider):
    """OpenRouter provider using the Anthropic-compatible messages API."""

    stream_chunk_mode: StreamChunkMode = "event"

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="OPENROUTER",
            default_base_url=OPENROUTER_BASE_URL,
        )

    def _build_request_body(self, request: Any) -> dict:
        """Internal helper for tests and direct request dispatch."""
        return build_request_body(
            request,
            thinking_enabled=self._is_thinking_enabled(request),
        )

    def _request_headers(self) -> dict[str, str]:
        """Return OpenRouter's Anthropic-compatible messages headers."""
        return {
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "anthropic-version": _ANTHROPIC_VERSION,
        }

    @staticmethod
    def _format_sse_event(event_name: str | None, data_text: str) -> str:
        """Format an SSE event from its event name and data payload."""
        lines: list[str] = []
        if event_name:
            lines.append(f"event: {event_name}")
        lines.extend(f"data: {line}" for line in data_text.splitlines())
        return "\n".join(lines) + "\n\n"

    @staticmethod
    def _parse_sse_event(event: str) -> tuple[str | None, str]:
        """Extract the event name and raw data payload from an SSE event."""
        event_name = None
        data_lines: list[str] = []
        for line in event.strip().splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        return event_name, "\n".join(data_lines)

    @staticmethod
    def _remap_index(
        payload: dict[str, Any], state: _SSEFilterState, *, create: bool
    ) -> int | None:
        """Return the downstream index for a content block event."""
        upstream_index = payload.get("index")
        if not isinstance(upstream_index, int):
            return None
        if upstream_index in state.dropped_indexes:
            return None
        mapped_index = state.index_map.get(upstream_index)
        if mapped_index is None and create:
            mapped_index = state.next_index
            state.index_map[upstream_index] = mapped_index
            state.next_index += 1
        return mapped_index

    def _filter_sse_event(self, event: str, state: _SSEFilterState) -> str | None:
        """Drop upstream thinking blocks and remap the remaining block indexes."""
        event_name, data_text = self._parse_sse_event(event)
        if not event_name or not data_text:
            return event

        try:
            payload = json.loads(data_text)
        except json.JSONDecodeError:
            return event

        if event_name == "content_block_start":
            block = payload.get("content_block")
            block_type = block.get("type") if isinstance(block, dict) else None
            upstream_index = payload.get("index")
            if isinstance(block_type, str) and "thinking" in block_type:
                if isinstance(upstream_index, int):
                    state.dropped_indexes.add(upstream_index)
                return None

            mapped_index = self._remap_index(payload, state, create=True)
            if mapped_index is not None:
                payload["index"] = mapped_index
            return self._format_sse_event(event_name, json.dumps(payload))

        if event_name == "content_block_delta":
            delta = payload.get("delta")
            delta_type = delta.get("type") if isinstance(delta, dict) else None
            if isinstance(delta_type, str) and "thinking" in delta_type:
                return None

            mapped_index = self._remap_index(payload, state, create=False)
            if mapped_index is None:
                return None
            payload["index"] = mapped_index
            return self._format_sse_event(event_name, json.dumps(payload))

        if event_name == "content_block_stop":
            mapped_index = self._remap_index(payload, state, create=False)
            if mapped_index is None:
                return None
            payload["index"] = mapped_index
            return self._format_sse_event(event_name, json.dumps(payload))

        return event

    def _new_stream_state(self, request: Any, *, thinking_enabled: bool) -> Any:
        """Create per-stream state for thinking block filtering."""
        return _SSEFilterState()

    def _transform_stream_event(
        self,
        event: str,
        state: Any,
        *,
        thinking_enabled: bool,
    ) -> str | None:
        """Drop thinking events when thinking is disabled."""
        if thinking_enabled:
            return event
        if isinstance(state, _SSEFilterState):
            return self._filter_sse_event(event, state)
        return event

    def _format_error_message(self, base_message: str, request_id: str | None) -> str:
        """Keep OpenRouter's existing request-id suffix format."""
        return append_request_id(base_message, request_id)

    def _emit_error_events(
        self,
        *,
        request: Any,
        input_tokens: int,
        error_message: str,
        sent_any_event: bool,
    ) -> Iterator[str]:
        """Emit the existing Anthropic SSE error shape."""
        sse = SSEBuilder(f"msg_{uuid.uuid4()}", request.model, input_tokens)
        if not sent_any_event:
            yield sse.message_start()
        yield from sse.emit_error(error_message)
        yield sse.message_delta("end_turn", 1)
        yield sse.message_stop()
