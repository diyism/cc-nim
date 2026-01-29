"""Platform-agnostic message models."""

from dataclasses import dataclass, field
from typing import Optional, Any
from datetime import datetime


@dataclass
class IncomingMessage:
    """
    Platform-agnostic incoming message.

    Adapters convert platform-specific events to this format.
    """

    text: str
    chat_id: str
    user_id: str
    message_id: str
    platform: str  # "telegram", "discord", "slack", etc.

    # Optional fields
    reply_to_message_id: Optional[str] = None
    username: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Platform-specific raw event for edge cases
    raw_event: Any = None

    def is_reply(self) -> bool:
        """Check if this message is a reply to another message."""
        return self.reply_to_message_id is not None


@dataclass
class OutgoingMessage:
    """
    Platform-agnostic outgoing message.

    The handler creates these, adapters convert to platform-specific format.
    """

    text: str
    chat_id: str

    # Optional fields
    reply_to: Optional[str] = None
    parse_mode: Optional[str] = "markdown"

    # For editing existing messages
    edit_message_id: Optional[str] = None


@dataclass
class MessageContext:
    """
    Context for message processing.

    Passed to handlers to track state across a conversation.
    """

    session_id: Optional[str] = None
    is_new_session: bool = True
    status_message_id: Optional[str] = None
