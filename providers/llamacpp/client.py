"""Llama.cpp provider implementation."""

from providers.anthropic_messages import AnthropicMessagesTransport
from providers.base import ProviderConfig
from providers.rate_limit import GlobalRateLimiter as GlobalRateLimiter

LLAMACPP_DEFAULT_BASE_URL = "http://localhost:8080/v1"


class LlamaCppProvider(AnthropicMessagesTransport):
    """Llama.cpp provider using native Anthropic Messages endpoint."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="LLAMACPP",
            default_base_url=LLAMACPP_DEFAULT_BASE_URL,
        )
