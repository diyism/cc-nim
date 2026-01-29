"""FastAPI application factory and configuration."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .routes import router
from .dependencies import cleanup_provider
from providers.exceptions import ProviderError
from config.settings import get_settings

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("server.log", encoding="utf-8", mode="w")],
)
logger = logging.getLogger(__name__)

# Suppress noisy uvicorn logs
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    settings = get_settings()
    logger.info("Starting Claude Code Proxy...")

    # Initialize messaging platform if configured
    messaging_platform = None
    try:
        if settings.telegram_api_id and settings.telegram_api_hash:
            from messaging.telegram import TelegramPlatform

            messaging_platform = TelegramPlatform()
            await messaging_platform.start()
            logger.info("Telegram platform started")
    except ImportError:
        logger.warning("Messaging module not yet available, skipping Telegram init")
    except Exception as e:
        logger.error(f"Failed to start messaging platform: {e}")

    # Store in app state for access in routes
    app.state.messaging_platform = messaging_platform

    yield

    # Cleanup
    if messaging_platform:
        await messaging_platform.stop()
    await cleanup_provider()
    logger.info("Server shutting down...")


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
