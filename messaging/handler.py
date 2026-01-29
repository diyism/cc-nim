"""
Claude Message Handler

Platform-agnostic Claude interaction logic.
Handles the core workflow of processing user messages via Claude CLI.
"""

import time
import asyncio
import logging
from typing import Optional, List, Tuple, TYPE_CHECKING

from .base import MessagingPlatform
from .models import IncomingMessage, MessageContext
from .session import SessionStore
from .queue import MessageQueueManager, QueuedMessage
from cli import CLISession, CLISessionManager, CLIParser
from config.settings import get_settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ClaudeMessageHandler:
    """
    Platform-agnostic handler for Claude interactions.

    This class contains the core logic for:
    - Processing user messages
    - Managing Claude CLI sessions
    - Updating status messages
    - Handling tool calls and thinking

    It works with any MessagingPlatform implementation.
    """

    def __init__(
        self,
        platform: MessagingPlatform,
        cli_manager: CLISessionManager,
        session_store: SessionStore,
        message_queue: MessageQueueManager,
    ):
        self.platform = platform
        self.cli_manager = cli_manager
        self.session_store = session_store
        self.message_queue = message_queue
        self._flood_wait_until = 0

    async def handle_message(self, incoming: IncomingMessage) -> None:
        """
        Main entry point for handling an incoming message.

        Determines if this is a new session or continuation,
        sends status message, and queues for processing.
        """
        # Check for commands
        if incoming.text == "/stop":
            await self._handle_stop_command(incoming)
            return

        if incoming.text == "/stats":
            await self._handle_stats_command(incoming)
            return

        # Filter out status messages (our own messages)
        if any(
            incoming.text.startswith(p)
            for p in ["⏳", "💭", "🔧", "✅", "❌", "🚀", "🤖", "📋", "📊", "🔄"]
        ):
            return

        # Check if this is a reply to an existing conversation
        session_id_to_resume = None
        if incoming.is_reply():
            session_id_to_resume = self.session_store.get_session_by_msg(
                incoming.chat_id,
                incoming.reply_to_message_id,
                incoming.platform,
            )
            if session_id_to_resume:
                logger.info(f"Found session {session_id_to_resume} for reply")

        # Send initial status message
        status_text = self._get_initial_status(session_id_to_resume)
        status_msg_id = await self.platform.send_message(
            incoming.chat_id,
            status_text,
            reply_to=incoming.message_id,
        )

        # Create queued message
        queued = QueuedMessage(
            incoming=incoming,
            status_message_id=status_msg_id,
        )

        # Determine session ID for queuing
        if session_id_to_resume:
            queue_session_id = session_id_to_resume
        else:
            # New session - use temp ID
            queue_session_id = f"pending_{incoming.message_id}"
            # Pre-register so replies work immediately
            self.session_store.save_session(
                session_id=queue_session_id,
                chat_id=incoming.chat_id,
                initial_msg_id=incoming.message_id,
                platform=incoming.platform,
            )
            self.session_store.update_last_message(queue_session_id, status_msg_id)

        # Enqueue for processing
        await self.message_queue.enqueue(
            session_id=queue_session_id,
            message=queued,
            processor=self._process_task,
        )

    async def _process_task(
        self,
        session_id_to_resume: Optional[str],
        queued: QueuedMessage,
    ) -> None:
        """Core task processor - handles a single Claude CLI interaction."""
        incoming = queued.incoming
        status_msg_id = queued.status_message_id
        chat_id = incoming.chat_id

        # Unified message accumulator
        message_parts: List[Tuple[str, str]] = []
        last_ui_update = 0.0
        captured_session_id = (
            session_id_to_resume
            if not session_id_to_resume.startswith("pending_")
            else None
        )
        temp_session_id = (
            session_id_to_resume
            if session_id_to_resume.startswith("pending_")
            else None
        )

        async def update_ui(status: Optional[str] = None, force: bool = False) -> None:
            nonlocal last_ui_update
            now = time.time()

            # Check flood wait
            if now < self._flood_wait_until:
                return

            if not force and now - last_ui_update < 1.0:
                return

            try:
                display = self._build_message(message_parts, status)
                if display:
                    await self.platform.edit_message(
                        chat_id, status_msg_id, display, parse_mode="markdown"
                    )
                    last_ui_update = now
            except Exception as e:
                logger.error(f"UI update failed: {e}")

        try:
            # Get or create CLI session
            try:
                (
                    cli_session,
                    session_or_temp_id,
                    is_new,
                ) = await self.cli_manager.get_or_create_session(
                    session_id=captured_session_id
                )
                if is_new:
                    temp_session_id = session_or_temp_id
                else:
                    captured_session_id = session_or_temp_id
            except RuntimeError as e:
                message_parts.append(("error", str(e)))
                await update_ui("⏳ **Session limit reached**", force=True)
                return

            # Process CLI events
            async for event_data in cli_session.start_task(
                incoming.text, session_id=captured_session_id
            ):
                if not isinstance(event_data, dict):
                    continue

                # Handle session_info event
                if event_data.get("type") == "session_info":
                    real_session_id = event_data.get("session_id")
                    if real_session_id and temp_session_id:
                        await self.cli_manager.register_real_session_id(
                            temp_session_id, real_session_id
                        )
                        captured_session_id = real_session_id
                        self.session_store.save_session(
                            session_id=real_session_id,
                            chat_id=chat_id,
                            initial_msg_id=incoming.message_id,
                            platform=incoming.platform,
                        )
                    continue

                parsed = CLIParser.parse_event(event_data)

                if not parsed:
                    continue

                if parsed["type"] == "thinking":
                    message_parts.append(("thinking", parsed["text"]))
                    await update_ui("🧠 **Claude is thinking...**")

                elif parsed["type"] == "content":
                    if parsed.get("text"):
                        if message_parts and message_parts[-1][0] == "content":
                            msg_type, content = message_parts[-1]
                            message_parts[-1] = ("content", content + parsed["text"])
                        else:
                            message_parts.append(("content", parsed["text"]))
                        await update_ui("🧠 **Claude is working...**")

                elif parsed["type"] == "tool_start":
                    names = [t.get("name") for t in parsed["tools"]]
                    message_parts.append(("tool", ", ".join(names)))
                    await update_ui("⏳ **Executing tools...**")

                elif parsed["type"] == "complete":
                    if not message_parts:
                        message_parts.append(("content", "Done."))
                    await update_ui("✅ **Complete**", force=True)

                    # Update session's last message
                    if captured_session_id:
                        self.session_store.update_last_message(
                            captured_session_id, status_msg_id
                        )

                elif parsed["type"] == "error":
                    message_parts.append(
                        ("error", parsed.get("message", "Unknown error"))
                    )
                    await update_ui("❌ **Error**", force=True)

        except asyncio.CancelledError:
            message_parts.append(("error", "Task was cancelled"))
            await update_ui("❌ **Cancelled**", force=True)
        except Exception as e:
            logger.error(f"Task failed: {e}")
            message_parts.append(("error", str(e)[:200]))
            await update_ui("💥 **Task Failed**", force=True)

    def _build_message(
        self,
        parts: List[Tuple[str, str]],
        status: Optional[str] = None,
    ) -> str:
        """Build unified message from parts."""
        lines = []
        if status:
            lines.append(status)
            lines.append("")

        for part_type, content in parts:
            if part_type == "thinking":
                display = content[:1200] + ("..." if len(content) > 1200 else "")
                lines.append(f"💭 **Thinking:**\n```\n{display}\n```")
            elif part_type == "tool":
                lines.append(f"🔧 **Tools:** `{content}`")
            elif part_type == "content":
                lines.append(content)
            elif part_type == "error":
                lines.append(f"⚠️ {content}")

        result = "\n".join(lines)
        # Truncate if too long
        if len(result) > 3800:
            result = "..." + result[-3795:]
            if result.count("```") % 2 != 0:
                result += "\n```"
        return result

    def _get_initial_status(self, session_id: Optional[str]) -> str:
        """Get initial status message text."""
        if session_id:
            if self.message_queue.is_session_busy(session_id):
                queue_size = self.message_queue.get_queue_size(session_id) + 1
                return f"📋 **Queued** (position {queue_size}) - waiting..."
            return "🔄 **Continuing conversation...**"

        stats = self.cli_manager.get_stats()
        if stats["active_sessions"] >= stats["max_sessions"]:
            return f"⏳ **Waiting for slot...** ({stats['active_sessions']}/{stats['max_sessions']})"
        return "⏳ **Launching new Claude CLI instance...**"

    async def _handle_stop_command(self, incoming: IncomingMessage) -> None:
        """Handle /stop command."""
        cancelled = await self.message_queue.cancel_all()
        await self.cli_manager.stop_all()
        await self.platform.send_message(
            incoming.chat_id,
            f"⏹ **Stopped.** Cancelled {len(cancelled)} pending messages.",
        )

    async def _handle_stats_command(self, incoming: IncomingMessage) -> None:
        """Handle /stats command."""
        stats = self.cli_manager.get_stats()
        await self.platform.send_message(
            incoming.chat_id,
            f"📊 **Stats**\n• Active: {stats['active_sessions']}\n• Max: {stats['max_sessions']}",
        )
