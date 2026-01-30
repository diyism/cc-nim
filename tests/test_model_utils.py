import pytest
from providers.model_utils import (
    strip_provider_prefixes,
    is_claude_model,
    normalize_model_name,
    get_original_model,
)


def test_strip_provider_prefixes():
    assert strip_provider_prefixes("anthropic/claude-3") == "claude-3"
    assert strip_provider_prefixes("openai/gpt-4") == "gpt-4"
    assert strip_provider_prefixes("gemini/gemini-pro") == "gemini-pro"
    assert strip_provider_prefixes("no-prefix") == "no-prefix"


def test_is_claude_model():
    assert is_claude_model("claude-3-sonnet") is True
    assert is_claude_model("claude-3-opus") is True
    assert is_claude_model("claude-3-haiku") is True
    assert is_claude_model("claude-2.1") is True
    assert is_claude_model("gpt-4") is False
    assert is_claude_model("gemini-pro") is False


def test_normalize_model_name_claude_maps_to_default():
    default = "target-model"
    # Strips prefix AND maps to default
    assert normalize_model_name("anthropic/claude-3-sonnet", default) == default
    assert normalize_model_name("claude-3-opus", default) == default


def test_normalize_model_name_non_claude_unchanged():
    default = "target-model"
    assert normalize_model_name("gpt-4", default) == "gpt-4"
    assert (
        normalize_model_name("openai/gpt-3.5-turbo", default) == "openai/gpt-3.5-turbo"
    )


def test_get_original_model():
    assert get_original_model("any-model") == "any-model"


def test_normalize_model_name_without_default(monkeypatch):
    monkeypatch.setenv("MODEL", "env-default-model")
    assert normalize_model_name("claude-3") == "env-default-model"
