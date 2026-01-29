import pytest
from fastapi.testclient import TestClient
from api.app import app
from api.dependencies import get_provider
from unittest.mock import AsyncMock, MagicMock
from providers.nvidia_nim import NvidiaNimProvider

# Mock provider
mock_provider = MagicMock(spec=NvidiaNimProvider)
mock_provider.complete = AsyncMock()
mock_provider.stream_response = AsyncMock()
mock_provider.convert_response = MagicMock()


def override_get_provider():
    return mock_provider


app.dependency_overrides[get_provider] = override_get_provider
client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_create_message_non_stream():
    mock_provider.complete.return_value = {"id": "123", "choices": []}
    mock_provider.convert_response.return_value = {
        "id": "msg_123",
        "type": "message",
        "role": "assistant",
        "model": "test-model",
        "content": [{"type": "text", "text": "Hello"}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    payload = {
        "model": "claude-3-sonnet",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 100,
        "stream": False,
    }

    response = client.post("/v1/messages", json=payload)
    assert response.status_code == 200
    assert response.json()["content"][0]["text"] == "Hello"
    mock_provider.complete.assert_called_once()


def test_model_mapping():
    # Test Haiku mapping
    payload_haiku = {
        "model": "claude-3-haiku-20240307",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 100,
    }
    client.post("/v1/messages", json=payload_haiku)
    args, _ = mock_provider.complete.call_args
    assert args[0].model != "claude-3-haiku-20240307"
    assert args[0].original_model == "claude-3-haiku-20240307"


def test_error_fallbacks():
    from providers.exceptions import (
        AuthenticationError,
        RateLimitError,
        OverloadedError,
    )

    # 1. Authentication Error (401)
    mock_provider.complete.side_effect = AuthenticationError("Invalid Key")
    response = client.post(
        "/v1/messages", json={"model": "test", "messages": [], "max_tokens": 10}
    )
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"

    # 2. Rate Limit (429)
    mock_provider.complete.side_effect = RateLimitError("Too Many Requests")
    response = client.post(
        "/v1/messages", json={"model": "test", "messages": [], "max_tokens": 10}
    )
    assert response.status_code == 429
    assert response.json()["error"]["type"] == "rate_limit_error"

    # 3. Overloaded (529)
    mock_provider.complete.side_effect = OverloadedError("Server Overloaded")
    response = client.post(
        "/v1/messages", json={"model": "test", "messages": [], "max_tokens": 10}
    )
    assert response.status_code == 529
    assert response.json()["error"]["type"] == "overloaded_error"
