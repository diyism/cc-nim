"""FastAPI application factory and configuration."""

import asyncio
import os
import signal

# Opt-in to future behavior for python-telegram-bot
os.environ["PTB_TIMEDELTA"] = "1"

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .routes import router
from .dependencies import cleanup_provider
from providers.exceptions import ProviderError
from config.settings import get_settings

from utils.signal_handlers import install_chained_signal_handlers

# Configure logging (atomic - only on true fresh start)
_settings = get_settings()
LOG_FILE = _settings.log_file

# Check if logging is already configured (e.g., hot reload)
# If handlers exist, skip setup to avoid clearing logs mid-session
if not logging.root.handlers:
    # Fresh start - clear log file and configure
    open(LOG_FILE, "w", encoding="utf-8").close()
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")],
    )

logger = logging.getLogger(__name__)

# Suppress noisy uvicorn logs
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

_SHUTDOWN_TIMEOUT_S = 5.0


async def _best_effort(
    name: str, awaitable, timeout_s: float = _SHUTDOWN_TIMEOUT_S
) -> None:
    """Run a shutdown step with timeout; never raise to callers."""
    try:
        await asyncio.wait_for(awaitable, timeout=timeout_s)
    except asyncio.CancelledError:
        # Shutdown tasks may be cancelled; treat as a successful "best effort".
        return
    except asyncio.TimeoutError:
        logger.warning(f"Shutdown step timed out: {name} ({timeout_s}s)")
    except Exception as e:
        logger.warning(f"Shutdown step failed: {name}: {type(e).__name__}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    settings = get_settings()
    logger.info("Starting Claude Code Proxy...")

    # Initialize messaging platform if configured
    messaging_platform = None
    message_handler = None
    cli_manager = None

    # Ctrl+C shutdown assist: chain SIGINT/SIGTERM to trigger early cleanup.
    shutdown_event = asyncio.Event()
    # Keep a plain counter because asyncio.Event state may lag behind
    # call_soon_threadsafe when signals arrive back-to-back.
    signal_count = {"n": 0}
    loop = asyncio.get_running_loop()

    def _on_signal(signum: int, _frame) -> None:
        signal_count["n"] += 1
        logger.warning(
            f"Signal received: {signum} (count={signal_count['n']}); requesting shutdown"
        )
        # On Windows + uvicorn, shutdown can hang indefinitely when
        # timeout_graceful_shutdown is None and there are stuck connections/tasks.
        # A second signal should always force termination.
        if signal_count["n"] >= 2:
            logger.error("Second shutdown signal; forcing exit")
            try:
                from cli.process_registry import kill_all_best_effort

                kill_all_best_effort()
            finally:
                os._exit(130)
        try:
            loop.call_soon_threadsafe(shutdown_event.set)
        except Exception:
            # Best-effort fallback; should still be safe if we're already on-loop.
            shutdown_event.set()

    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        # Windows Ctrl+Break.
        signals.append(signal.SIGBREAK)

    restore_signal_handlers = install_chained_signal_handlers(
        signals=signals,
        handler=_on_signal,
    )
    logger.info(f"Installed shutdown signal handlers: {[int(s) for s in signals]}")

    async def _early_shutdown_worker() -> None:
        await shutdown_event.wait()
        logger.warning("Early shutdown: running best-effort cleanup steps")
        try:
            from cli.process_registry import kill_all_best_effort

            kill_all_best_effort()
        except Exception:
            pass

        # Try to stop the Telegram poller quickly; lifespan cleanup will also run.
        mp = getattr(app.state, "messaging_platform", None)
        cm = getattr(app.state, "cli_manager", None)
        mh = getattr(app.state, "message_handler", None)
        if mp:
            await _best_effort(
                "early.messaging_platform.stop", mp.stop(), timeout_s=2.0
            )
        if mh:
            await _best_effort(
                "early.message_handler.stop_all_tasks",
                mh.stop_all_tasks(),
                timeout_s=2.0,
            )
        if cm:
            await _best_effort(
                "early.cli_manager.stop_all", cm.stop_all(), timeout_s=2.0
            )
        try:
            from messaging.limiter import MessagingRateLimiter

            await _best_effort(
                "early.MessagingRateLimiter.shutdown_instance",
                MessagingRateLimiter.shutdown_instance(),
                timeout_s=2.0,
            )
        except Exception:
            pass

    early_shutdown_task = asyncio.create_task(_early_shutdown_worker())

    try:
        # Use the messaging factory to create the right platform
        from messaging.factory import create_messaging_platform

        messaging_platform = create_messaging_platform(
            platform_type=settings.messaging_platform,
            bot_token=settings.telegram_bot_token,
            allowed_user_id=settings.allowed_telegram_user_id,
        )

        if messaging_platform:
            from messaging.handler import ClaudeMessageHandler
            from messaging.session import SessionStore
            from cli.manager import CLISessionManager

            # Setup workspace - CLI runs in allowed_dir if set (e.g. project root)
            workspace = (
                os.path.abspath(settings.allowed_dir)
                if settings.allowed_dir
                else os.getcwd()
            )
            os.makedirs(workspace, exist_ok=True)

            # Session data stored in agent_workspace
            data_path = os.path.abspath(settings.claude_workspace)
            os.makedirs(data_path, exist_ok=True)

            api_url = f"http://{settings.host}:{settings.port}/v1"
            allowed_dirs = [workspace] if settings.allowed_dir else []
            cli_manager = CLISessionManager(
                workspace_path=workspace,
                api_url=api_url,
                allowed_dirs=allowed_dirs,
                max_sessions=settings.max_cli_sessions,
            )

            # Initialize session store
            session_store = SessionStore(
                storage_path=os.path.join(data_path, "sessions.json")
            )

            # Create and register message handler
            message_handler = ClaudeMessageHandler(
                platform=messaging_platform,
                cli_manager=cli_manager,
                session_store=session_store,
            )

            # Restore tree state if available
            saved_trees = session_store.get_all_trees()
            if saved_trees:
                logger.info(f"Restoring {len(saved_trees)} conversation trees...")
                from messaging.tree_queue import TreeQueueManager

                message_handler.tree_queue = TreeQueueManager.from_dict(
                    {
                        "trees": saved_trees,
                        "node_to_tree": session_store.get_node_mapping(),
                    },
                    queue_update_callback=message_handler._update_queue_positions,
                    node_started_callback=message_handler._mark_node_processing,
                )
                # Reconcile restored state - anything PENDING/IN_PROGRESS is lost across restart
                if message_handler.tree_queue.cleanup_stale_nodes() > 0:
                    # Sync back and save
                    tree_data = message_handler.tree_queue.to_dict()
                    session_store.sync_from_tree_data(
                        tree_data["trees"], tree_data["node_to_tree"]
                    )

            # Wire up the handler
            messaging_platform.on_message(message_handler.handle_message)

            # Start the platform
            await messaging_platform.start()
            logger.info(
                f"{messaging_platform.name} platform started with message handler"
            )

    except ImportError as e:
        logger.warning(f"Messaging module import error: {e}")
    except Exception as e:
        logger.error(f"Failed to start messaging platform: {e}")
        import traceback

        logger.error(traceback.format_exc())

    # Store in app state for access in routes
    app.state.messaging_platform = messaging_platform
    app.state.message_handler = message_handler
    app.state.cli_manager = cli_manager

    yield

    # Cleanup
    logger.info("Shutdown requested, cleaning up...")
    if messaging_platform:
        await _best_effort("messaging_platform.stop", messaging_platform.stop())
    if cli_manager:
        await _best_effort("cli_manager.stop_all", cli_manager.stop_all())
    await _best_effort("cleanup_provider", cleanup_provider())

    # Ensure background limiter worker doesn't keep the loop alive.
    try:
        from messaging.limiter import MessagingRateLimiter

        await _best_effort(
            "MessagingRateLimiter.shutdown_instance",
            MessagingRateLimiter.shutdown_instance(),
            timeout_s=2.0,
        )
    except Exception:
        # Limiter may never have been imported/initialized.
        pass

    # Stop the early-shutdown worker and restore signal handlers.
    try:
        early_shutdown_task.cancel()
        await _best_effort("early_shutdown_task", early_shutdown_task, timeout_s=1.0)
    except Exception:
        pass
    try:
        restore_signal_handlers()
    except Exception:
        pass

    logger.info("Server shut down cleanly")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Claude Code Proxy",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Register routes
    app.include_router(router)

    # Exception handlers
    @app.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, exc: ProviderError):
        """Handle provider-specific errors and return Anthropic format."""
        logger.error(f"Provider Error: {exc.error_type} - {exc.message}")
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_anthropic_format(),
        )

    @app.exception_handler(Exception)
    async def general_error_handler(request: Request, exc: Exception):
        """Handle general errors and return Anthropic format."""
        logger.error(f"General Error: {str(exc)}")
        import traceback

        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": "An unexpected error occurred.",
                },
            },
        )

    return app


# Default app instance for uvicorn
app = create_app()
