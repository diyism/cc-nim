"""Application runtime composition and lifecycle ownership."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from loguru import logger

from config.settings import Settings, get_settings

from .dependencies import cleanup_provider

_SHUTDOWN_TIMEOUT_S = 5.0


async def best_effort(
    name: str, awaitable: Any, timeout_s: float = _SHUTDOWN_TIMEOUT_S
) -> None:
    """Run a shutdown step with timeout; never raise to callers."""
    try:
        await asyncio.wait_for(awaitable, timeout=timeout_s)
    except TimeoutError:
        logger.warning(f"Shutdown step timed out: {name} ({timeout_s}s)")
    except Exception as e:
        logger.warning(f"Shutdown step failed: {name}: {type(e).__name__}: {e}")


def warn_if_process_auth_token(settings: Settings) -> None:
    """Warn when server auth was implicitly inherited from the shell."""
    uses_process_token = getattr(settings, "uses_process_anthropic_auth_token", None)
    if callable(uses_process_token) and uses_process_token():
        logger.warning(
            "ANTHROPIC_AUTH_TOKEN is set in the process environment but not in "
            "a configured .env file. The proxy will require that token. Add "
            "ANTHROPIC_AUTH_TOKEN= to .env to disable proxy auth, or set the "
            "same token in .env to make server auth explicit."
        )


@dataclass(slots=True)
class AppRuntime:
    """Own optional messaging, CLI, session, and provider runtime resources."""

    app: FastAPI
    settings: Settings
    provider_cleanup: Callable[[], Awaitable[None]] = cleanup_provider
    messaging_platform: Any = None
    message_handler: Any = None
    cli_manager: Any = None

    @classmethod
    def for_app(
        cls,
        app: FastAPI,
        settings: Settings | None = None,
        provider_cleanup: Callable[[], Awaitable[None]] = cleanup_provider,
    ) -> AppRuntime:
        return cls(
            app=app,
            settings=settings or get_settings(),
            provider_cleanup=provider_cleanup,
        )

    async def startup(self) -> None:
        logger.info("Starting Claude Code Proxy...")
        warn_if_process_auth_token(self.settings)
        await self._start_messaging_if_configured()
        self._publish_state()

    async def shutdown(self) -> None:
        if self.message_handler and hasattr(self.message_handler, "session_store"):
            try:
                self.message_handler.session_store.flush_pending_save()
            except Exception as e:
                logger.warning(f"Session store flush on shutdown: {e}")

        logger.info("Shutdown requested, cleaning up...")
        if self.messaging_platform:
            await best_effort("messaging_platform.stop", self.messaging_platform.stop())
        if self.cli_manager:
            await best_effort("cli_manager.stop_all", self.cli_manager.stop_all())
        await best_effort("cleanup_provider", self.provider_cleanup())
        await self._shutdown_limiter()
        logger.info("Server shut down cleanly")

    async def _start_messaging_if_configured(self) -> None:
        try:
            from messaging.platforms.factory import create_messaging_platform

            self.messaging_platform = create_messaging_platform(
                platform_type=self.settings.messaging_platform,
                bot_token=self.settings.telegram_bot_token,
                allowed_user_id=self.settings.allowed_telegram_user_id,
                discord_bot_token=self.settings.discord_bot_token,
                allowed_discord_channels=self.settings.allowed_discord_channels,
            )

            if self.messaging_platform:
                await self._start_message_handler()

        except ImportError as e:
            logger.warning(f"Messaging module import error: {e}")
        except Exception as e:
            logger.error(f"Failed to start messaging platform: {e}")
            import traceback

            logger.error(traceback.format_exc())

    async def _start_message_handler(self) -> None:
        from cli.manager import CLISessionManager
        from messaging.handler import ClaudeMessageHandler
        from messaging.session import SessionStore

        workspace = (
            os.path.abspath(self.settings.allowed_dir)
            if self.settings.allowed_dir
            else os.getcwd()
        )
        os.makedirs(workspace, exist_ok=True)

        data_path = os.path.abspath(self.settings.claude_workspace)
        os.makedirs(data_path, exist_ok=True)

        api_url = f"http://{self.settings.host}:{self.settings.port}/v1"
        allowed_dirs = [workspace] if self.settings.allowed_dir else []
        plans_dir_abs = os.path.abspath(
            os.path.join(self.settings.claude_workspace, "plans")
        )
        plans_directory = os.path.relpath(plans_dir_abs, workspace)
        self.cli_manager = CLISessionManager(
            workspace_path=workspace,
            api_url=api_url,
            allowed_dirs=allowed_dirs,
            plans_directory=plans_directory,
            claude_bin=getattr(self.settings, "claude_cli_bin", "claude"),
        )

        session_store = SessionStore(
            storage_path=os.path.join(data_path, "sessions.json")
        )
        self.message_handler = ClaudeMessageHandler(
            platform=self.messaging_platform,
            cli_manager=self.cli_manager,
            session_store=session_store,
        )
        self._restore_tree_state(session_store)

        self.messaging_platform.on_message(self.message_handler.handle_message)
        await self.messaging_platform.start()
        logger.info(
            f"{self.messaging_platform.name} platform started with message handler"
        )

    def _restore_tree_state(self, session_store: Any) -> None:
        saved_trees = session_store.get_all_trees()
        if not saved_trees:
            return

        logger.info(f"Restoring {len(saved_trees)} conversation trees...")
        from messaging.trees.queue_manager import TreeQueueManager

        self.message_handler.replace_tree_queue(
            TreeQueueManager.from_dict(
                {
                    "trees": saved_trees,
                    "node_to_tree": session_store.get_node_mapping(),
                },
                queue_update_callback=self.message_handler.update_queue_positions,
                node_started_callback=self.message_handler.mark_node_processing,
            )
        )
        if self.message_handler.tree_queue.cleanup_stale_nodes() > 0:
            tree_data = self.message_handler.tree_queue.to_dict()
            session_store.sync_from_tree_data(
                tree_data["trees"], tree_data["node_to_tree"]
            )

    def _publish_state(self) -> None:
        self.app.state.messaging_platform = self.messaging_platform
        self.app.state.message_handler = self.message_handler
        self.app.state.cli_manager = self.cli_manager

    async def _shutdown_limiter(self) -> None:
        try:
            from messaging.limiter import MessagingRateLimiter

            await best_effort(
                "MessagingRateLimiter.shutdown_instance",
                MessagingRateLimiter.shutdown_instance(),
                timeout_s=2.0,
            )
        except Exception:
            pass
