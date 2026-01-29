"""
Message Queue Manager for Messaging Platforms

Handles queuing of messages when Claude is busy processing a request.
Messages are processed one-by-one in order per session.
Platform-agnostic: works with any messaging platform.
"""

import asyncio
import logging
from typing import Callable, Awaitable, Dict, Optional, List, Any
from dataclasses import dataclass

from .models import IncomingMessage

logger = logging.getLogger(__name__)


@dataclass
class QueuedMessage:
    """A message waiting to be processed."""

    incoming: IncomingMessage
    status_message_id: str  # The status message to update
    context: Any = None  # Additional context if needed


class SessionQueue:
    """Queue for a single session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.queue: asyncio.Queue[QueuedMessage] = asyncio.Queue()
        self.is_processing = False
        self.current_task: Optional[asyncio.Task] = None
        self.current_message: Optional[QueuedMessage] = None


class MessageQueueManager:
    """
    Manages per-session message queues.

    When a session is busy, new messages are queued and processed
    one-by-one after the current request completes.
    """

    def __init__(self):
        self._queues: Dict[str, SessionQueue] = {}
        self._lock = asyncio.Lock()

    def _get_or_create_queue(self, session_id: str) -> SessionQueue:
        """Get existing queue or create new one for session."""
        if session_id not in self._queues:
            self._queues[session_id] = SessionQueue(session_id)
        return self._queues[session_id]

    def is_session_busy(self, session_id: str) -> bool:
        """Check if a session is currently processing a request."""
        if session_id not in self._queues:
            return False
        return self._queues[session_id].is_processing

    async def enqueue(
        self,
        session_id: str,
        message: QueuedMessage,
        processor: Callable[[str, QueuedMessage], Awaitable[None]],
    ) -> bool:
        """
        Add a message to the session's queue.

        If the session is not busy, processing starts immediately.
        If busy, the message is queued for later processing.

        Args:
            session_id: Claude session ID
            message: The queued message data
            processor: Async function to process the message

        Returns:
            True if message was queued (session busy), False if processed immediately
        """
        async with self._lock:
            sq = self._get_or_create_queue(session_id)

            if sq.is_processing:
                # Session is busy, queue the message
                await sq.queue.put(message)
                queue_size = sq.queue.qsize()
                logger.info(
                    f"Queued message for session {session_id}, queue size: {queue_size}"
                )
                return True
            else:
                # Session is free, start processing
                sq.is_processing = True

        # Process outside the lock
        sq = self._queues[session_id]
        sq.current_task = asyncio.create_task(
            self._process_message(session_id, message, processor)
        )
        return False

    async def _process_message(
        self,
        session_id: str,
        message: QueuedMessage,
        processor: Callable[[str, QueuedMessage], Awaitable[None]],
    ) -> None:
        """Process a single message and then check the queue."""
        sq = self._queues.get(session_id)
        if sq:
            sq.current_message = message
        try:
            await processor(session_id, message)
        except asyncio.CancelledError:
            logger.info(f"Task for session {session_id} was cancelled")
            raise
        except Exception as e:
            logger.error(f"Error processing message for session {session_id}: {e}")
        finally:
            if sq:
                sq.current_message = None
            # Check if there are more messages in the queue
            await self._process_next(session_id, processor)

    async def _process_next(
        self,
        session_id: str,
        processor: Callable[[str, QueuedMessage], Awaitable[None]],
    ) -> None:
        """Process the next message in queue, if any."""
        async with self._lock:
            if session_id not in self._queues:
                return

            sq = self._queues[session_id]

            if sq.queue.empty():
                # No more messages, mark session as free
                sq.is_processing = False
                logger.debug(f"Session {session_id} queue empty, marking as free")
                return

            # Get next message
            try:
                next_msg = sq.queue.get_nowait()
                logger.info(f"Processing next queued message for session {session_id}")
            except asyncio.QueueEmpty:
                sq.is_processing = False
                return

        # Process next message (outside lock)
        sq.current_task = asyncio.create_task(
            self._process_message(session_id, next_msg, processor)
        )

    def get_queue_size(self, session_id: str) -> int:
        """Get the number of messages waiting in a session's queue."""
        if session_id not in self._queues:
            return 0
        return self._queues[session_id].queue.qsize()

    def cancel_session(self, session_id: str) -> List[QueuedMessage]:
        """
        Cancel all queued messages for a session and the running task.

        Returns:
            List of messages that were cancelled (including the current one if any)
        """
        if session_id not in self._queues:
            return []

        sq = self._queues[session_id]
        cancelled_messages = []

        # 1. Cancel running task
        if sq.current_task and not sq.current_task.done():
            sq.current_task.cancel()
            if sq.current_message:
                cancelled_messages.append(sq.current_message)

        # 2. Clear queue
        while not sq.queue.empty():
            try:
                msg = sq.queue.get_nowait()
                cancelled_messages.append(msg)
            except asyncio.QueueEmpty:
                break

        sq.is_processing = False
        logger.info(
            f"Cancelled {len(cancelled_messages)} messages for session {session_id}"
        )
        return cancelled_messages

    async def cancel_all(self) -> List[QueuedMessage]:
        """
        Cancel everything in all sessions.

        Returns:
            List of all cancelled messages across all sessions.
        """
        async with self._lock:
            all_cancelled = []
            session_ids = list(self._queues.keys())
            for sid in session_ids:
                all_cancelled.extend(self.cancel_session(sid))
            return all_cancelled
