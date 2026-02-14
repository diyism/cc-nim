import signal

from utils.signal_handlers import install_chained_signal_handlers


def test_install_chained_signal_handlers_calls_prev_and_new_handler():
    calls = []

    def prev(signum, frame):
        calls.append(("prev", signum))

    old = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, prev)

    try:

        def ours(signum, frame):
            calls.append(("ours", signum))

        restore = install_chained_signal_handlers(signals=[signal.SIGINT], handler=ours)

        try:
            h = signal.getsignal(signal.SIGINT)
            assert callable(h)
            # Call the installed handler directly (don't actually raise SIGINT).
            h(signal.SIGINT, None)  # type: ignore[misc]
        finally:
            restore()

    finally:
        signal.signal(signal.SIGINT, old)

    assert calls == [("ours", signal.SIGINT), ("prev", signal.SIGINT)]
