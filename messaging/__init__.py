"""Platform-agnostic messaging layer."""

from .base import MessagingPlatform
from .models import IncomingMessage, OutgoingMessage
from .handler import ClaudeMessageHandler
from .session import SessionStore
from .queue import MessageQueueManager

__all__ = [
    "MessagingPlatform",
    "IncomingMessage",
    "OutgoingMessage",
    "ClaudeMessageHandler",
    "SessionStore",
    "MessageQueueManager",
]
