"""Llama.cpp provider implementation."""

from providers.anthropic_compat import AnthropicMessagesProvider
from providers.base import ProviderConfig

LLAMACPP_DEFAULT_BASE_URL = "http://localhost:8080/v1"


class LlamaCppProvider(AnthropicMessagesProvider):
    """Llama.cpp provider using native Anthropic Messages API endpoint."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="LLAMACPP",
            default_base_url=LLAMACPP_DEFAULT_BASE_URL,
        )
