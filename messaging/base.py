"""Abstract base class for messaging platforms."""

from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional, Any
from .models import IncomingMessage


class MessagingPlatform(ABC):
    """
    Base class for all messaging platform adapters.

    Implement this to add support for Telegram, Discord, Slack, etc.
    """

    name: str = "base"

    @abstractmethod
    async def start(self) -> None:
        """Initialize and connect to the messaging platform."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Disconnect and cleanup resources."""
        pass

    @abstractmethod
    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> str:
        """
        Send a message to a chat.

        Args:
            chat_id: The chat/channel ID to send to
            text: Message content
            reply_to: Optional message ID to reply to
            parse_mode: Optional formatting mode ("markdown", "html")

        Returns:
            The message ID of the sent message
        """
        pass

    @abstractmethod
    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        text: str,
        parse_mode: Optional[str] = None,
    ) -> None:
        """
        Edit an existing message.

        Args:
            chat_id: The chat/channel ID
            message_id: The message ID to edit
            text: New message content
            parse_mode: Optional formatting mode
        """
        pass

    @abstractmethod
    def on_message(
        self,
        handler: Callable[[IncomingMessage], Awaitable[None]],
    ) -> None:
        """
        Register a message handler callback.

        The handler will be called for each incoming message.

        Args:
            handler: Async function that processes incoming messages
        """
        pass

    @property
    def is_connected(self) -> bool:
        """Check if the platform is connected."""
        return False
