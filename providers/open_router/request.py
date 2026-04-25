"""Request builder for OpenRouter provider."""

from collections.abc import Sequence
from typing import Any

from loguru import logger
from pydantic import BaseModel

OPENROUTER_DEFAULT_MAX_TOKENS = 81920

_REQUEST_FIELDS = (
    "model",
    "messages",
    "system",
    "max_tokens",
    "stop_sequences",
    "stream",
    "temperature",
    "top_p",
    "top_k",
    "metadata",
    "tools",
    "tool_choice",
    "thinking",
    "extra_body",
    "original_model",
    "resolved_provider_model",
)

_INTERNAL_FIELDS = {
    "thinking",
    "extra_body",
    "original_model",
    "resolved_provider_model",
}


def _serialize_value(value: Any) -> Any:
    """Convert Pydantic models and lightweight objects into JSON-ready values."""
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        return {
            key: _serialize_value(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_serialize_value(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if hasattr(value, "__dict__"):
        return {
            key: _serialize_value(item)
            for key, item in vars(value).items()
            if not key.startswith("_") and item is not None
        }
    return value


def _dump_request_fields(request_data: Any) -> dict[str, Any]:
    """Extract the public request fields we forward to OpenRouter."""
    if isinstance(request_data, BaseModel):
        return request_data.model_dump(exclude_none=True)

    dumped: dict[str, Any] = {}
    for field in _REQUEST_FIELDS:
        value = getattr(request_data, field, None)
        if value is not None:
            dumped[field] = _serialize_value(value)
    return dumped


def build_request_body(request_data: Any, *, thinking_enabled: bool) -> dict:
    """Build an Anthropic-format request body for OpenRouter's messages API."""
    logger.debug(
        "OPENROUTER_REQUEST: conversion start model={} msgs={}",
        getattr(request_data, "model", "?"),
        len(getattr(request_data, "messages", [])),
    )

    dumped_request = _dump_request_fields(request_data)
    request_extra = dumped_request.pop("extra_body", None)
    body = {
        key: value
        for key, value in dumped_request.items()
        if key not in _INTERNAL_FIELDS
    }

    if isinstance(request_extra, dict):
        body.update(request_extra)

    body["stream"] = True
    if body.get("max_tokens") is None:
        body["max_tokens"] = OPENROUTER_DEFAULT_MAX_TOKENS

    if thinking_enabled:
        body.setdefault("reasoning", {"enabled": True})

    logger.debug(
        "OPENROUTER_REQUEST: conversion done model={} msgs={} tools={}",
        body.get("model"),
        len(body.get("messages", [])),
        len(body.get("tools", [])),
    )
    return body
