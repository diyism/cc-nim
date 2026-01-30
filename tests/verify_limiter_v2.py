import asyncio
import time
import os
from messaging.limiter import GlobalRateLimiter

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_compaction_and_hang():
    # Set small rate for testing
    os.environ["MESSAGING_RATE_LIMIT"] = "1"
    os.environ["MESSAGING_RATE_WINDOW"] = "0.5"  # Fast for testing

    limiter = await GlobalRateLimiter.get_instance()

    call_counts = {}

    async def mock_edit(msg_id, content):
        call_counts[msg_id] = call_counts.get(msg_id, 0) + 1
        logger.info(f"Executing actual Telegram edit for {msg_id}: {content}")
        await asyncio.sleep(0.1)  # Simulate network lag
        return f"result_{content}"

    print("\n--- Starting Hang/Multi-Future Test ---")

    msg_id = "test_msg_123"

    # We will enqueue 3 edits and await all of them.
    # Previously, the 2nd and 3rd would HANG.

    async def task(i):
        logger.info(f"Task {i} started, enqueuing edit...")
        res = await limiter.enqueue(
            lambda i=i: mock_edit(msg_id, f"v{i}"), dedup_key=f"edit:{msg_id}"
        )
        logger.info(f"Task {i} completed with: {res}")
        return res

    start_time = time.time()

    # Run tasks concurrently
    results = await asyncio.gather(task(1), task(2), task(3))

    end_time = time.time()
    duration = end_time - start_time

    print(f"\nAll tasks finished in {duration:.2f}s")
    print(f"Results: {results}")
    print(f"Call counts: {call_counts}")

    # Check that they all got the LAST result
    for res in results:
        assert res == "result_v3", f"Expected result_v3, got {res}"

    # Check that they didn't hang (should be < 1s given the compaction)
    assert duration < 2.0, "Tasks took too long, might have hung or not compacted"

    # Check call counts:
    # T1 might go through immediately or be compacted if T2/T3 arrive fast enough.
    # Given the loop speed, we expect 1-2 calls.
    assert call_counts[msg_id] <= 2, f"Too many calls: {call_counts[msg_id]}"

    print("\nPASSED: All futures resolved, no hang detected.")


if __name__ == "__main__":
    # Fix encoding for windows terminal to avoid Unicode print crash
    import sys
    import io

    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    asyncio.run(test_compaction_and_hang())
