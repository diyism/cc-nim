"""LM Studio provider implementation."""

from providers.anthropic_compat import AnthropicMessagesProvider
from providers.base import ProviderConfig

LMSTUDIO_DEFAULT_BASE_URL = "http://localhost:1234/v1"


class LMStudioProvider(AnthropicMessagesProvider):
    """LM Studio provider using native Anthropic Messages API endpoint."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="LMSTUDIO",
            default_base_url=LMSTUDIO_DEFAULT_BASE_URL,
        )
