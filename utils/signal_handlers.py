"""Signal handler helpers.

We run under asyncio + uvicorn on Windows. Ctrl+C (SIGINT) is normally handled by
uvicorn, but some background tasks (Telegram polling, subprocesses) may keep the
process alive longer than expected. These helpers let us *chain* our own handler
without breaking any existing handler already installed by uvicorn.
"""

from __future__ import annotations

import signal
import threading
from types import FrameType
from typing import Any, Callable, Dict, Iterable, Optional


def _call_prev(prev: Any, signum: int, frame: Optional[FrameType]) -> None:
    if not callable(prev):
        return
    try:
        prev(signum, frame)
    except TypeError:
        # Some handlers only accept (signum).
        prev(signum)  # type: ignore[misc]


def install_chained_signal_handlers(
    *,
    signals: Iterable[int],
    handler: Callable[[int, Optional[FrameType]], None],
) -> Callable[[], None]:
    """Install `handler` for each signal, while preserving any existing handler.

    Returns a restore() function that puts the previous handlers back.
    """
    # `signal.signal(...)` only works in the main thread. During tests (FastAPI
    # TestClient), lifespan runs in a worker thread, so we must no-op.
    if threading.current_thread() is not threading.main_thread():
        return lambda: None

    previous: Dict[int, Any] = {}

    for sig in signals:
        prev = signal.getsignal(sig)
        previous[sig] = prev

        def _wrapped(signum: int, frame: Optional[FrameType], _prev=prev) -> None:
            handler(signum, frame)
            _call_prev(_prev, signum, frame)

        signal.signal(sig, _wrapped)

    def restore() -> None:
        for sig, prev in previous.items():
            signal.signal(sig, prev)  # type: ignore[arg-type]

    return restore
