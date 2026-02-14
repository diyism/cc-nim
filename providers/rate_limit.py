"""Global rate limiter for API requests."""

import asyncio
import random
import time
import logging
from typing import Any, Callable, Optional, TypeVar

import openai
from aiolimiter import AsyncLimiter

T = TypeVar("T")

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

    def __init__(self, rate_limit: int = 40, rate_window: float = 60.0):
        # Prevent double initialization in singleton
        if hasattr(self, "_initialized"):
            return

        self.limiter = AsyncLimiter(rate_limit, rate_window)
        self._blocked_until: float = 0
        self._lock = asyncio.Lock()
        self._initialized = True

        logger.info(
            f"GlobalRateLimiter (Provider) initialized ({rate_limit} req / {rate_window}s)"
        )

    @classmethod
    def get_instance(
        cls,
        rate_limit: Optional[int] = None,
        rate_window: Optional[float] = None,
    ) -> "GlobalRateLimiter":
        """Get or create the singleton instance.

        Args:
            rate_limit: Requests per window (only used on first creation)
            rate_window: Window in seconds (only used on first creation)
        """
        if cls._instance is None:
            cls._instance = cls(
                rate_limit=rate_limit or 40,
                rate_window=rate_window or 60.0,
            )
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

    async def execute_with_retry(
        self,
        fn: Callable[..., Any],
        *args: Any,
        max_retries: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 60.0,
        jitter: float = 1.0,
        **kwargs: Any,
    ) -> Any:
        """Execute an async callable with rate limiting and retry on 429.

        Waits for the token bucket before each attempt. On 429, applies
        exponential backoff with jitter before retrying.

        Args:
            fn: Async callable to execute.
            max_retries: Maximum number of retry attempts after the first failure.
            base_delay: Base delay in seconds for exponential backoff.
            max_delay: Maximum delay cap in seconds.
            jitter: Maximum random jitter in seconds added to each delay.

        Returns:
            The result of the callable.

        Raises:
            The last exception if all retries are exhausted.
        """
        last_exc: Optional[Exception] = None

        for attempt in range(1 + max_retries):
            await self.wait_if_blocked()

            try:
                return await fn(*args, **kwargs)
            except openai.RateLimitError as e:
                last_exc = e
                if attempt >= max_retries:
                    logger.warning(
                        f"Rate limit retry exhausted after {max_retries} retries"
                    )
                    break

                delay = min(base_delay * (2 ** attempt), max_delay)
                delay += random.uniform(0, jitter)
                logger.warning(
                    f"Rate limited (429), attempt {attempt + 1}/{max_retries + 1}. "
                    f"Retrying in {delay:.1f}s..."
                )
                self.set_blocked(delay)
                await asyncio.sleep(delay)

        raise last_exc  # type: ignore[misc]
