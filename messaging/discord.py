"""Backward-compatible re-export. Use messaging.platforms.discord for new code."""

from .platforms.discord import (
    DISCORD_AVAILABLE,
    DISCORD_MESSAGE_LIMIT,
    DiscordPlatform,
    _get_discord,
    _parse_allowed_channels,
)

__all__ = [
    "DISCORD_AVAILABLE",
    "DISCORD_MESSAGE_LIMIT",
    "DiscordPlatform",
    "_get_discord",
    "_parse_allowed_channels",
]
