"""Backward-compatible re-export. Use messaging.trees.queue_manager for new code."""

from .trees.queue_manager import (
    MessageNode,
    MessageState,
    MessageTree,
    TreeQueueManager,
)

__all__ = ["MessageNode", "MessageState", "MessageTree", "TreeQueueManager"]
