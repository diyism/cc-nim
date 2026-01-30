import asyncio
import logging
from typing import Optional, Callable, Awaitable
from .base import MessagingPlatform
from .models import IncomingMessage
from .rate_limiter import GlobalRateLimiter

logger = logging.getLogger(__name__)


class RateLimitedPlatform(MessagingPlatform):
    """
    A wrapper around MessagingPlatform that ensures outgoing messages
    are sent according to the global rate limit.
    """

    def __init__(
        self,
        platform: MessagingPlatform,
        rate_limit: int = 1,
        rate_window: float = 1.0,
    ):
        self._platform = platform
        self._limiter = GlobalRateLimiter(calls=rate_limit, period=rate_window)

        logger.info(
            f"RateLimitedPlatform initialized with {rate_limit} calls per {rate_window}s"
        )

    @property
    def name(self) -> str:
        return f"rate_limited_{self._platform.name}"

    async def start(self) -> None:
        await self._platform.start()

    async def stop(self) -> None:
        self._limiter.stop()
        await self._platform.stop()

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> str:
        """Queues the message for sending."""

        async def _send():
            return await self._platform.send_message(
                chat_id, text, reply_to, parse_mode
            )

        return await self._limiter.execute(_send)

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        text: str,
        parse_mode: Optional[str] = None,
    ) -> None:
        """Queues the message for editing."""

        async def _edit():
            return await self._platform.edit_message(
                chat_id, message_id, text, parse_mode
            )

        await self._limiter.execute(_edit)

    def on_message(
        self,
        handler: Callable[[IncomingMessage], Awaitable[None]],
    ) -> None:
        self._platform.on_message(handler)

    @property
    def is_connected(self) -> bool:
        return self._platform.is_connected
