"""Loguru-based structured logging configuration.

All logs are written to server.log as JSON lines for full traceability.
Stdlib logging is intercepted and funneled to loguru.
"""

import logging
from loguru import logger


_configured = False


class InterceptHandler(logging.Handler):
    """Redirect stdlib logging to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def configure_logging(log_file: str, *, force: bool = False) -> None:
    """Configure loguru with JSON output to log_file and intercept stdlib logging.

    Idempotent: skips if already configured (e.g. hot reload).
    Use force=True to reconfigure (e.g. in tests with a different log path).
    """
    global _configured
    if _configured and not force:
        return
    _configured = True

    # Remove default loguru handler (writes to stderr)
    logger.remove()

    # Truncate log file on fresh start for clean debugging
    open(log_file, "w", encoding="utf-8").close()

    # Add file sink: JSON lines, DEBUG level, full traceability
    logger.add(
        log_file,
        level="DEBUG",
        serialize=True,
        encoding="utf-8",
        mode="a",
    )

    # Intercept stdlib logging: route all root logger output to loguru
    intercept = InterceptHandler()
    logging.root.handlers = [intercept]
    logging.root.setLevel(logging.DEBUG)
