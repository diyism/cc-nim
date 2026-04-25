"""Backward-compatible token counting import for API route handlers."""

from core.anthropic import get_token_count

__all__ = ["get_token_count"]
