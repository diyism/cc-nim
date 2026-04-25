"""Model routing for Claude-compatible requests."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from config.settings import Settings

from .models.anthropic import MessagesRequest, TokenCountRequest


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    original_model: str
    provider_id: str
    provider_model: str
    provider_model_ref: str


class ModelRouter:
    """Resolve incoming Claude model names to configured provider/model pairs."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def resolve(self, claude_model_name: str) -> ResolvedModel:
        provider_model_ref = self._settings.resolve_model(claude_model_name)
        provider_id = Settings.parse_provider_type(provider_model_ref)
        provider_model = Settings.parse_model_name(provider_model_ref)
        if provider_model != claude_model_name:
            logger.debug(
                "MODEL MAPPING: '{}' -> '{}'", claude_model_name, provider_model
            )
        return ResolvedModel(
            original_model=claude_model_name,
            provider_id=provider_id,
            provider_model=provider_model,
            provider_model_ref=provider_model_ref,
        )

    def resolve_messages_request(self, request: MessagesRequest) -> MessagesRequest:
        """Return a routed copy of a MessagesRequest."""
        original_model = request.original_model or request.model
        resolved = self.resolve(original_model)
        routed = request.model_copy(deep=True)
        routed.original_model = resolved.original_model
        routed.resolved_provider_model = resolved.provider_model_ref
        routed.model = resolved.provider_model
        return routed

    def resolve_token_count_request(
        self, request: TokenCountRequest
    ) -> TokenCountRequest:
        """Return a token-count request copy with provider model name applied."""
        resolved = self.resolve(request.model)
        return request.model_copy(update={"model": resolved.provider_model}, deep=True)
