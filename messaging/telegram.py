"""Backward-compatible re-export. Use messaging.platforms.telegram for new code."""

from .platforms.telegram import (
    TELEGRAM_AVAILABLE,
    TelegramPlatform,
)

# Re-export telegram.error types when python-telegram-bot is installed
__all__ = ["TELEGRAM_AVAILABLE", "TelegramPlatform"]
try:
    from telegram.error import NetworkError, RetryAfter, TelegramError

    __all__ += ["NetworkError", "RetryAfter", "TelegramError"]
except ImportError:
    pass
