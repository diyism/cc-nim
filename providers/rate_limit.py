"""Global rate limiter for API requests."""

import asyncio
import time
import logging
import os
from typing import Optional
from aiolimiter import AsyncLimiter

logger = logging.getLogger(__name__)


class GlobalRateLimiter:
    """
    Global singleton rate limiter that blocks all requests
    when a rate limit error is encountered (reactive) and
    throttles requests (proactive) using aiolimiter.

    Proactive limits - throttles requests to stay within API limits.
    Reactive limits - pauses all requests when a 429 is hit.
    """

    _instance: Optional["GlobalRateLimiter"] = None

    def __init__(self):
        # Prevent double initialization in singleton
        if hasattr(self, "_initialized"):
            return

        rate_limit = int(os.getenv("NVIDIA_NIM_RATE_LIMIT", "40"))
        rate_window = float(os.getenv("NVIDIA_NIM_RATE_WINDOW", "60.0"))

        self.limiter = AsyncLimiter(rate_limit, rate_window)
        self._blocked_until: float = 0
        self._lock = asyncio.Lock()
        self._initialized = True

        logger.info(
            f"GlobalRateLimiter (Provider) initialized ({rate_limit} req / {rate_window}s)"
        )

    @classmethod
    def get_instance(cls) -> "GlobalRateLimiter":
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    async def wait_if_blocked(self) -> bool:
        """
        Wait if currently rate limited or throttle to meet quota.

        Returns:
            True if was reactively blocked and waited, False otherwise.
        """
        # 1. Reactive check: Wait if someone hit a 429
        waited_reactively = False
        now = time.time()
        if now < self._blocked_until:
            wait_time = self._blocked_until - now
            logger.warning(
                f"Global provider rate limit active (reactive), waiting {wait_time:.1f}s..."
            )
            await asyncio.sleep(wait_time)
            waited_reactively = True

        # 2. Proactive check: Acquire slot from aiolimiter
        async with self.limiter:
            return waited_reactively

    def set_blocked(self, seconds: float = 60) -> None:
        """
        Set global block for specified seconds (reactive).

        Args:
            seconds: How long to block (default 60s)
        """
        self._blocked_until = time.time() + seconds
        logger.warning(f"Global provider rate limit set for {seconds:.1f}s (reactive)")

    def is_blocked(self) -> bool:
        """Check if currently reactively blocked."""
        return time.time() < self._blocked_until

    def remaining_wait(self) -> float:
        """Get remaining reactive wait time in seconds."""
        return max(0, self._blocked_until - time.time())
