"""Backward-compatible re-export. Use messaging.trees.data for new code."""

from .trees.data import MessageNode, MessageState, MessageTree

__all__ = ["MessageNode", "MessageState", "MessageTree"]
