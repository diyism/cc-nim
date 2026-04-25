"""Provider descriptors, factory, and runtime registry."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Literal

from config.settings import Settings
from providers.base import BaseProvider, ProviderConfig
from providers.deepseek import DEEPSEEK_BASE_URL, DeepSeekProvider
from providers.exceptions import AuthenticationError
from providers.llamacpp import LlamaCppProvider
from providers.lmstudio import LMStudioProvider
from providers.nvidia_nim import NVIDIA_NIM_BASE_URL, NvidiaNimProvider
from providers.open_router import (
    OPENROUTER_BASE_URL,
    OpenRouterChatProvider,
    OpenRouterProvider,
)

TransportType = Literal["openai_chat", "anthropic_messages"]
ProviderFactory = Callable[[ProviderConfig, Settings], BaseProvider]


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    transport_type: TransportType
    capabilities: tuple[str, ...]
    credential_env: str | None = None
    credential_url: str | None = None
    default_base_url: str | None = None
    base_url_attr: str | None = None
    proxy_attr: str | None = None


PROVIDER_DESCRIPTORS: dict[str, ProviderDescriptor] = {
    "nvidia_nim": ProviderDescriptor(
        provider_id="nvidia_nim",
        transport_type="openai_chat",
        credential_env="NVIDIA_NIM_API_KEY",
        credential_url="https://build.nvidia.com/settings/api-keys",
        default_base_url=NVIDIA_NIM_BASE_URL,
        proxy_attr="nvidia_nim_proxy",
        capabilities=("chat", "streaming", "tools", "thinking", "rate_limit"),
    ),
    "open_router": ProviderDescriptor(
        provider_id="open_router",
        transport_type="anthropic_messages",
        credential_env="OPENROUTER_API_KEY",
        credential_url="https://openrouter.ai/keys",
        default_base_url=OPENROUTER_BASE_URL,
        proxy_attr="open_router_proxy",
        capabilities=("chat", "streaming", "tools", "thinking", "native_anthropic"),
    ),
    "deepseek": ProviderDescriptor(
        provider_id="deepseek",
        transport_type="openai_chat",
        credential_env="DEEPSEEK_API_KEY",
        credential_url="https://platform.deepseek.com/api_keys",
        default_base_url=DEEPSEEK_BASE_URL,
        capabilities=("chat", "streaming", "thinking"),
    ),
    "lmstudio": ProviderDescriptor(
        provider_id="lmstudio",
        transport_type="anthropic_messages",
        default_base_url="http://localhost:1234/v1",
        base_url_attr="lm_studio_base_url",
        proxy_attr="lmstudio_proxy",
        capabilities=("chat", "streaming", "tools", "native_anthropic", "local"),
    ),
    "llamacpp": ProviderDescriptor(
        provider_id="llamacpp",
        transport_type="anthropic_messages",
        default_base_url="http://localhost:8080/v1",
        base_url_attr="llamacpp_base_url",
        proxy_attr="llamacpp_proxy",
        capabilities=("chat", "streaming", "tools", "native_anthropic", "local"),
    ),
}


def _create_nvidia_nim(config: ProviderConfig, settings: Settings) -> BaseProvider:
    return NvidiaNimProvider(config, nim_settings=settings.nim)


def _create_open_router(config: ProviderConfig, settings: Settings) -> BaseProvider:
    if settings.openrouter_transport == "openai":
        return OpenRouterChatProvider(config)
    return OpenRouterProvider(config)


def _create_deepseek(config: ProviderConfig, settings: Settings) -> BaseProvider:
    return DeepSeekProvider(config)


def _create_lmstudio(config: ProviderConfig, settings: Settings) -> BaseProvider:
    return LMStudioProvider(config)


def _create_llamacpp(config: ProviderConfig, settings: Settings) -> BaseProvider:
    return LlamaCppProvider(config)


PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "nvidia_nim": _create_nvidia_nim,
    "open_router": _create_open_router,
    "deepseek": _create_deepseek,
    "lmstudio": _create_lmstudio,
    "llamacpp": _create_llamacpp,
}


def _string_attr(settings: Settings, attr_name: str | None, default: str = "") -> str:
    if attr_name is None:
        return default
    value = getattr(settings, attr_name, default)
    return value if isinstance(value, str) else default


def _credential_for(provider_id: str, settings: Settings) -> str:
    if provider_id == "nvidia_nim":
        return settings.nvidia_nim_api_key
    if provider_id == "open_router":
        return settings.open_router_api_key
    if provider_id == "deepseek":
        return settings.deepseek_api_key
    if provider_id == "lmstudio":
        return "lm-studio"
    if provider_id == "llamacpp":
        return "llamacpp"
    return ""


def _require_credential(descriptor: ProviderDescriptor, credential: str) -> None:
    if descriptor.credential_env is None:
        return
    if credential and credential.strip():
        return
    message = f"{descriptor.credential_env} is not set. Add it to your .env file."
    if descriptor.credential_url:
        message = f"{message} Get a key at {descriptor.credential_url}"
    raise AuthenticationError(message)


def build_provider_config(
    descriptor: ProviderDescriptor, settings: Settings
) -> ProviderConfig:
    credential = _credential_for(descriptor.provider_id, settings)
    _require_credential(descriptor, credential)
    base_url = _string_attr(
        settings, descriptor.base_url_attr, descriptor.default_base_url or ""
    )
    proxy = _string_attr(settings, descriptor.proxy_attr)
    return ProviderConfig(
        api_key=credential,
        base_url=base_url or descriptor.default_base_url,
        rate_limit=settings.provider_rate_limit,
        rate_window=settings.provider_rate_window,
        max_concurrency=settings.provider_max_concurrency,
        http_read_timeout=settings.http_read_timeout,
        http_write_timeout=settings.http_write_timeout,
        http_connect_timeout=settings.http_connect_timeout,
        enable_thinking=settings.enable_thinking,
        proxy=proxy,
    )


def create_provider(provider_id: str, settings: Settings) -> BaseProvider:
    descriptor = PROVIDER_DESCRIPTORS.get(provider_id)
    if descriptor is None:
        supported = "', '".join(PROVIDER_DESCRIPTORS)
        raise ValueError(
            f"Unknown provider_type: '{provider_id}'. Supported: '{supported}'"
        )

    config = build_provider_config(descriptor, settings)
    factory = PROVIDER_FACTORIES.get(provider_id)
    if factory is None:
        raise AssertionError(f"Unhandled provider descriptor: {provider_id}")
    return factory(config, settings)


class ProviderRegistry:
    """Cache and clean up provider instances by provider id."""

    def __init__(self, providers: MutableMapping[str, BaseProvider] | None = None):
        self._providers = providers if providers is not None else {}

    def get(self, provider_id: str, settings: Settings) -> BaseProvider:
        if provider_id not in self._providers:
            self._providers[provider_id] = create_provider(provider_id, settings)
        return self._providers[provider_id]

    async def cleanup(self) -> None:
        for provider in self._providers.values():
            await provider.cleanup()
        self._providers.clear()
