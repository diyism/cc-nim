"""Providers package - implement your own provider by extending BaseProvider."""

from .anthropic_messages import AnthropicMessagesTransport
from .base import BaseProvider, ProviderConfig
from .deepseek import DeepSeekProvider
from .exceptions import (
    APIError,
    AuthenticationError,
    InvalidRequestError,
    OverloadedError,
    ProviderError,
    RateLimitError,
)
from .llamacpp import LlamaCppProvider
from .lmstudio import LMStudioProvider
from .nvidia_nim import NvidiaNimProvider
from .open_router import OpenRouterChatProvider, OpenRouterProvider
from .openai_compat import OpenAIChatTransport, OpenAICompatibleProvider

__all__ = [
    "APIError",
    "AnthropicMessagesTransport",
    "AuthenticationError",
    "BaseProvider",
    "DeepSeekProvider",
    "InvalidRequestError",
    "LMStudioProvider",
    "LlamaCppProvider",
    "NvidiaNimProvider",
    "OpenAIChatTransport",
    "OpenAICompatibleProvider",
    "OpenRouterChatProvider",
    "OpenRouterProvider",
    "OverloadedError",
    "ProviderConfig",
    "ProviderError",
    "RateLimitError",
]
