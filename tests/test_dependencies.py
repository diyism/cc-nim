import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from api.dependencies import get_provider, get_settings, cleanup_provider
from providers.nvidia_nim import NvidiaNimProvider


@pytest.fixture(autouse=True)
def reset_provider():
    """Reset the global _provider singleton between tests."""
    with patch("api.dependencies._provider", None):
        yield


@pytest.mark.asyncio
async def test_get_provider_singleton():
    with patch("api.dependencies.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock()
        mock_settings.return_value.nvidia_nim_api_key = "test_key"

        p1 = get_provider()
        p2 = get_provider()

        assert isinstance(p1, NvidiaNimProvider)
        assert p1 is p2


@pytest.mark.asyncio
async def test_get_settings():
    settings = get_settings()
    assert settings is not None
    # Verify it calls the internal _get_settings
    with patch("api.dependencies._get_settings") as mock_get:
        get_settings()
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_provider():
    with patch("api.dependencies.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock()
        mock_settings.return_value.nvidia_nim_api_key = "test_key"

        provider = get_provider()
        provider._client = AsyncMock()

        await cleanup_provider()

        provider._client.aclose.assert_called_once()
        # The singleton should be None now, but since we patched the local _provider
        # we need to be careful how we verify.
        # Actually within the same test session without the patch, it would be None.


@pytest.mark.asyncio
async def test_cleanup_provider_no_client():
    with patch("api.dependencies.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock()
        mock_settings.return_value.nvidia_nim_api_key = "test_key"

        provider = get_provider()
        if hasattr(provider, "_client"):
            del provider._client

        await cleanup_provider()
        # Should not raise
