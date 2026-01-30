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

        # specific components for structured display
        components = {
            "thinking": [],  # List[str]
            "tools": [],  # List[str]
            "subagents": [],  # List[str]
            "content": [],  # List[str]
            "errors": [],  # List[str]
        }

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
                display = self._build_message(components, status)
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
                components["errors"].append(str(e))
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

                parsed_list = CLIParser.parse_event(event_data)

                for parsed in parsed_list:
                    if parsed["type"] == "thinking":
                        # append to the last thinking block if valid, or just simple list
                        components["thinking"].append(parsed["text"])
                        await update_ui("🧠 **Claude is thinking...**")

                    elif parsed["type"] == "content":
                        if parsed.get("text"):
                            components["content"].append(parsed["text"])
                            await update_ui("🧠 **Claude is working...**")

                    elif parsed["type"] == "tool_start":
                        names = [t.get("name") for t in parsed.get("tools", [])]
                        components["tools"].extend(names)
                        await update_ui("⏳ **Executing tools...**")

                    elif parsed["type"] == "subagent_start":
                        tasks = parsed.get("tasks", [])
                        components["subagents"].extend(tasks)
                        await update_ui("🤖 **Subagent working...**")

                    elif parsed["type"] == "complete":
                        if not any(components.values()):
                            components["content"].append("Done.")
                        await update_ui("✅ **Complete**", force=True)

                        # Update session's last message
                        if captured_session_id:
                            self.session_store.update_last_message(
                                captured_session_id, status_msg_id
                            )

                    elif parsed["type"] == "error":
                        components["errors"].append(
                            parsed.get("message", "Unknown error")
                        )
                        await update_ui("❌ **Error**", force=True)

        except asyncio.CancelledError:
            components["errors"].append("Task was cancelled")
            await update_ui("❌ **Cancelled**", force=True)
        except Exception as e:
            logger.error(f"Task failed: {e}")
            components["errors"].append(str(e)[:200])
            await update_ui("💥 **Task Failed**", force=True)

    def _build_message(
        self,
        components: dict,
        status: Optional[str] = None,
    ) -> str:
        """
        Build unified message with specific order:
        1. Thinking
        2. Tools
        3. Subagents
        4. Content
        5. Errors
        6. Status (Bottom)
        """
        lines = []

        # 1. Thinking
        if components["thinking"]:
            full_thinking = "".join(components["thinking"])
            # limit thinking length visually
            display = full_thinking
            if len(display) > 800:
                display = display[:795] + "..."
            lines.append(f"💭 **Thinking:**\n```\n{display}\n```")

        # 2. Tools
        if components["tools"]:
            # Unique tools to avoid clutter
            unique_tools = []
            seen = set()
            for t in components["tools"]:
                if t not in seen:
                    unique_tools.append(t)
                    seen.add(t)
            lines.append(f"🛠 **Tools:** `{', '.join(unique_tools)}`")

        # 3. Subagents
        if components["subagents"]:
            for task in components["subagents"]:
                lines.append(f"🤖 **Subagent:** `{task}`")

        # 4. Content
        if components["content"]:
            # Join content parts
            full_content = "".join(components["content"])
            lines.append(full_content)

        # 5. Errors
        if components["errors"]:
            for err in components["errors"]:
                lines.append(f"⚠️ **Error:** `{err}`")

        # 6. Status (Bottom)
        if status:
            lines.append("")  # spacer
            lines.append(status)

        result = "\n".join(lines)

        # Truncate if too long (Telegram limit ~4096)
        # We leave some buffer
        if len(result) > 3800:
            result = "..." + result[-3795:]
            # basic attempt to fix unclosed code blocks if we truncated the top
            # but usually we want to preserve the bottom (content/status)
            pass

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
