"""Base provider interface - extend this to implement your own provider."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel


class ProviderConfig(BaseModel):
    """Configuration for a provider.

    Base fields apply to all providers. Provider-specific parameters
    (e.g. NIM temperature, top_p) are passed by the provider constructor.
    """

    api_key: str
    base_url: str | None = None
    rate_limit: int | None = None
    rate_window: int = 60
    max_concurrency: int = 5
    http_read_timeout: float = 300.0
    http_write_timeout: float = 10.0
    http_connect_timeout: float = 2.0
    opus_enable_thinking: bool = True
    sonnet_enable_thinking: bool = True
    haiku_enable_thinking: bool = True
    model_enable_thinking: bool = True
    proxy: str = ""


class BaseProvider(ABC):
    """Base class for all providers. Extend this to add your own."""

    def __init__(self, config: ProviderConfig):
        self._config = config

    def _is_thinking_enabled(self, request: Any) -> bool:
        """Return whether thinking should be enabled for this request."""
        thinking = getattr(request, "thinking", None)
        request_enabled = (
            thinking.enabled
            if thinking is not None and hasattr(thinking, "enabled")
            else True
        )
        request_model = getattr(request, "original_model", None) or getattr(
            request, "model", ""
        )
        model_enabled = self._resolve_model_thinking_enabled(str(request_model))
        return model_enabled and request_enabled

    def _resolve_model_thinking_enabled(self, model: str) -> bool:
        """Return the configured thinking flag for a Claude model family."""
        model_lower = model.lower()
        if "opus" in model_lower:
            return self._config.opus_enable_thinking
        if "haiku" in model_lower:
            return self._config.haiku_enable_thinking
        if "sonnet" in model_lower:
            return self._config.sonnet_enable_thinking
        return self._config.model_enable_thinking

    @abstractmethod
    async def cleanup(self) -> None:
        """Release any resources held by this provider."""

    @abstractmethod
    async def stream_response(
        self,
        request: Any,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream response in Anthropic SSE format."""
        if False:
            yield ""  # Required for ty/mypy to accept abstract async generator
