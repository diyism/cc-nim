"""Platform-agnostic messaging layer."""

from .base import CLISession, MessagingPlatform, SessionManagerInterface
from .event_parser import parse_cli_event
from .handler import ClaudeMessageHandler
from .models import IncomingMessage
from .session import SessionStore
from .tree_data import MessageNode, MessageState, MessageTree
from .tree_queue import TreeQueueManager

__all__ = [
    "CLISession",
    "ClaudeMessageHandler",
    "IncomingMessage",
    "MessageNode",
    "MessageState",
    "MessageTree",
    "MessagingPlatform",
    "SessionManagerInterface",
    "SessionStore",
    "TreeQueueManager",
    "parse_cli_event",
]
