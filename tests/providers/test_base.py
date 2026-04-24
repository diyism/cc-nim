from providers.base import BaseProvider, ProviderConfig


class DummyProvider(BaseProvider):
    async def cleanup(self) -> None:
        return None

    async def stream_response(self, request, input_tokens=0, *, request_id=None):
        if False:
            yield ""


class DummyThinking:
    def __init__(self, enabled: bool):
        self.enabled = enabled


class DummyRequest:
    def __init__(
        self,
        *,
        model: str,
        original_model: str | None = None,
        thinking: DummyThinking | None = None,
    ):
        self.model = model
        self.original_model = original_model
        self.thinking = thinking


def test_is_thinking_enabled_uses_original_model_family():
    provider = DummyProvider(
        ProviderConfig(
            api_key="test",
            opus_enable_thinking=False,
            model_enable_thinking=True,
        )
    )
    request = DummyRequest(
        model="provider-model",
        original_model="claude-opus-4-20250514",
        thinking=DummyThinking(True),
    )

    assert provider._is_thinking_enabled(request) is False


def test_is_thinking_enabled_falls_back_to_request_model():
    provider = DummyProvider(
        ProviderConfig(
            api_key="test",
            sonnet_enable_thinking=False,
            model_enable_thinking=True,
        )
    )
    request = DummyRequest(model="claude-sonnet-4-20250514")

    assert provider._is_thinking_enabled(request) is False


def test_is_thinking_enabled_unknown_model_uses_fallback_flag():
    provider = DummyProvider(
        ProviderConfig(api_key="test", model_enable_thinking=False)
    )
    request = DummyRequest(model="provider-model")

    assert provider._is_thinking_enabled(request) is False


def test_is_thinking_enabled_respects_request_disable():
    provider = DummyProvider(ProviderConfig(api_key="test", opus_enable_thinking=True))
    request = DummyRequest(
        model="provider-model",
        original_model="claude-opus-4-20250514",
        thinking=DummyThinking(False),
    )

    assert provider._is_thinking_enabled(request) is False
