import asyncio
import os
import time
import logging
import sys

# Add current directory to path
sys.path.append(os.getcwd())

from providers.rate_limit import GlobalRateLimiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_proactive_throttling():
    print("\n--- Testing Proactive Throttling (3 req / 1 sec) ---")
    os.environ["NVIDIA_NIM_RATE_LIMIT"] = "3"
    os.environ["NVIDIA_NIM_RATE_WINDOW"] = "1.0"

    GlobalRateLimiter.reset_instance()
    limiter = GlobalRateLimiter.get_instance()

    start_time = time.time()

    async def call_limiter(i):
        await limiter.wait_if_blocked()
        print(f"[{time.time() - start_time:.2f}s] Request {i} passed")

    print("Sending 5 requests sequentially...")
    # 3 should pass immediately, 4th and 5th should wait
    for i in range(5):
        await call_limiter(i)

    total_time = time.time() - start_time
    print(f"All requests completed in {total_time:.2f}s")

    # 5 requests with limit 3 per 1s:
    # R0, R1, R2 at ~0s
    # R3 waits until R0 is 1s old -> ~1s
    # R4 waits until R1 is 1s old -> ~1s
    if total_time >= 0.9:  # Allow some jitter
        print("[SUCCESS] Proactive throttling working!")
    else:
        print(f"[FAILURE] Proactive throttling failed! Took only {total_time:.2f}s")


async def test_reactive_blocking():
    print("\n--- Testing Reactive Blocking ---")
    GlobalRateLimiter.reset_instance()
    limiter = GlobalRateLimiter.get_instance()

    start_time = time.time()

    print("Setting manual block for 2s...")
    limiter.set_blocked(2)

    async def call_limiter(i):
        waited = await limiter.wait_if_blocked()
        print(
            f"[{time.time() - start_time:.2f}s] Request {i} passed (waited reactively: {waited})"
        )
        return waited

    results = await asyncio.gather(*[call_limiter(i) for i in range(2)])

    total_time = time.time() - start_time
    print(f"Requests completed in {total_time:.2f}s")

    if total_time >= 1.9 and any(results):
        print("[SUCCESS] Reactive blocking working!")
    else:
        print(f"[FAILURE] Reactive blocking failed! Took only {total_time:.2f}s")


async def main():
    try:
        await test_proactive_throttling()
        await test_reactive_blocking()
    except Exception as e:
        print(f"Error during verification: {e}")
    finally:
        print("\nVerification complete.")


if __name__ == "__main__":
    asyncio.run(main())
