"""Backward-compatible re-export. Use messaging.platforms.base for new code."""

from .platforms.base import (
    CLISession,
    MessagingPlatform,
    SessionManagerInterface,
)

__all__ = ["CLISession", "MessagingPlatform", "SessionManagerInterface"]
