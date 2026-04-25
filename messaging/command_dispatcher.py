"""Command parsing and dispatch for messaging handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from .models import IncomingMessage

CommandHandler = Callable[[IncomingMessage], Awaitable[None]]


class SupportsMessagingCommands(Protocol):
    async def _handle_clear_command(self, incoming: IncomingMessage) -> None: ...

    async def _handle_stop_command(self, incoming: IncomingMessage) -> None: ...

    async def _handle_stats_command(self, incoming: IncomingMessage) -> None: ...


def parse_command_base(text: str | None) -> str:
    """Return the slash command without bot mention suffix."""
    parts = (text or "").strip().split()
    cmd = parts[0] if parts else ""
    return cmd.split("@", 1)[0] if cmd else ""


def message_kind_for_command(command_base: str) -> str:
    """Return the persistence kind for an incoming message."""
    return "command" if command_base.startswith("/") else "content"


async def dispatch_command(
    handler: SupportsMessagingCommands,
    incoming: IncomingMessage,
    command_base: str,
) -> bool:
    """Dispatch a known command and return whether it was handled."""
    commands: dict[str, CommandHandler] = {
        "/clear": handler._handle_clear_command,
        "/stop": handler._handle_stop_command,
        "/stats": handler._handle_stats_command,
    }
    command = commands.get(command_base)
    if command is None:
        return False
    await command(incoming)
    return True
