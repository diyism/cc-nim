"""
Claude Message Handler

Platform-agnostic Claude interaction logic.
Handles the core workflow of processing user messages via Claude CLI.
Uses tree-based queuing for message ordering.
"""

import time
import asyncio
import logging
import re
from typing import List, Optional

from markdown_it import MarkdownIt

from .base import MessagingPlatform, SessionManagerInterface
from .models import IncomingMessage
from .session import SessionStore
from .tree_queue import TreeQueueManager, MessageNode, MessageState, MessageTree
from .event_parser import parse_cli_event

logger = logging.getLogger(__name__)


MDV2_SPECIAL_CHARS = set("\\_*[]()~`>#+-=|{}.!")

MDV2_LINK_ESCAPE = set("\\)")

_MD = MarkdownIt("commonmark", {"html": False, "breaks": False})
_MD.enable("strikethrough")
_MD.enable("table")


_TABLE_SEP_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_FENCE_RE = re.compile(r"^\s*```")


def _is_gfm_table_header_line(line: str) -> bool:
    # Must be pipe-delimited with at least 2 columns and not be the separator line.
    if "|" not in line:
        return False
    if _TABLE_SEP_RE.match(line):
        return False
    stripped = line.strip()
    parts = [p.strip() for p in stripped.strip("|").split("|")]
    parts = [p for p in parts if p != ""]
    return len(parts) >= 2


def _normalize_gfm_tables(text: str) -> str:
    """
    Many LLMs emit tables immediately after a paragraph line (no blank line).
    Markdown-it will treat that as a softbreak within the paragraph, so the
    table extension won't trigger. Insert a blank line before detected tables.

    We only do this outside fenced code blocks.
    """
    lines = text.splitlines()
    if len(lines) < 2:
        return text

    out_lines: List[str] = []
    in_fence = False

    for idx, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue

        if (
            not in_fence
            and idx + 1 < len(lines)
            and _is_gfm_table_header_line(line)
            and _TABLE_SEP_RE.match(lines[idx + 1])
        ):
            if out_lines and out_lines[-1].strip() != "":
                indent = re.match(r"^(\s*)", line).group(1)
                # A line of only whitespace counts as a blank line and preserves
                # list indentation contexts (tables inside list items).
                out_lines.append(indent)

        out_lines.append(line)

    return "\n".join(out_lines)


def escape_md_v2(text: str) -> str:
    """Escape text for Telegram MarkdownV2."""
    return "".join(f"\\{ch}" if ch in MDV2_SPECIAL_CHARS else ch for ch in text)


def escape_md_v2_code(text: str) -> str:
    """Escape text for Telegram MarkdownV2 code spans/blocks."""
    return text.replace("\\", "\\\\").replace("`", "\\`")


def escape_md_v2_link_url(text: str) -> str:
    """Escape URL for Telegram MarkdownV2 link destination."""
    return "".join(f"\\{ch}" if ch in MDV2_LINK_ESCAPE else ch for ch in text)


def mdv2_bold(text: str) -> str:
    return f"*{escape_md_v2(text)}*"


def mdv2_code_inline(text: str) -> str:
    return f"`{escape_md_v2_code(text)}`"


def format_status(emoji: str, label: str, suffix: Optional[str] = None) -> str:
    base = f"{emoji} {mdv2_bold(label)}"
    if suffix:
        return f"{base} {escape_md_v2(suffix)}"
    return base


def render_markdown_to_mdv2(text: str) -> str:
    """Render common Markdown into Telegram MarkdownV2."""
    if not text:
        return ""

    text = _normalize_gfm_tables(text)
    tokens = _MD.parse(text)

    def render_inline_table_plain(children) -> str:
        # Keep table cells as plain text for stable monospace alignment.
        out: List[str] = []
        for tok in children:
            if tok.type == "text":
                out.append(tok.content)
            elif tok.type == "code_inline":
                out.append(tok.content)
            elif tok.type in {"softbreak", "hardbreak"}:
                out.append(" ")
            elif tok.type == "image":
                # markdown-it-py stores alt text in content for images.
                if tok.content:
                    out.append(tok.content)
        return "".join(out)

    def render_inline_plain(children) -> str:
        out: List[str] = []
        for tok in children:
            if tok.type == "text":
                out.append(escape_md_v2(tok.content))
            elif tok.type == "code_inline":
                out.append(escape_md_v2(tok.content))
            elif tok.type in {"softbreak", "hardbreak"}:
                out.append("\n")
        return "".join(out)

    def render_inline(children) -> str:
        out: List[str] = []
        i = 0
        while i < len(children):
            tok = children[i]
            t = tok.type
            if t == "text":
                out.append(escape_md_v2(tok.content))
            elif t in {"softbreak", "hardbreak"}:
                out.append("\n")
            elif t == "em_open":
                out.append("_")
            elif t == "em_close":
                out.append("_")
            elif t == "strong_open":
                out.append("*")
            elif t == "strong_close":
                out.append("*")
            elif t == "s_open":
                out.append("~")
            elif t == "s_close":
                out.append("~")
            elif t == "code_inline":
                out.append(f"`{escape_md_v2_code(tok.content)}`")
            elif t == "link_open":
                href = ""
                if tok.attrs:
                    if isinstance(tok.attrs, dict):
                        href = tok.attrs.get("href", "")
                    else:
                        for key, val in tok.attrs:
                            if key == "href":
                                href = val
                                break
                inner_tokens = []
                i += 1
                while i < len(children) and children[i].type != "link_close":
                    inner_tokens.append(children[i])
                    i += 1
                link_text = ""
                for child in inner_tokens:
                    if child.type == "text":
                        link_text += child.content
                    elif child.type == "code_inline":
                        link_text += child.content
                out.append(
                    f"[{escape_md_v2(link_text)}]({escape_md_v2_link_url(href)})"
                )
            elif t == "image":
                href = ""
                alt = tok.content or ""
                if tok.attrs:
                    if isinstance(tok.attrs, dict):
                        href = tok.attrs.get("src", "")
                    else:
                        for key, val in tok.attrs:
                            if key == "src":
                                href = val
                                break
                if alt:
                    out.append(f"{escape_md_v2(alt)} ({escape_md_v2_link_url(href)})")
                else:
                    out.append(escape_md_v2_link_url(href))
            else:
                out.append(escape_md_v2(tok.content or ""))
            i += 1
        return "".join(out)

    out: List[str] = []
    list_stack: List[dict] = []
    pending_prefix: Optional[str] = None
    blockquote_level = 0
    in_heading = False

    def apply_blockquote(val: str) -> str:
        if blockquote_level <= 0:
            return val
        prefix = "> " * blockquote_level
        return prefix + val.replace("\n", "\n" + prefix)

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        t = tok.type
        if t == "paragraph_open":
            pass
        elif t == "paragraph_close":
            out.append("\n")
        elif t == "heading_open":
            in_heading = True
        elif t == "heading_close":
            in_heading = False
            out.append("\n")
        elif t == "bullet_list_open":
            list_stack.append({"type": "bullet", "index": 1})
        elif t == "bullet_list_close":
            if list_stack:
                list_stack.pop()
            out.append("\n")
        elif t == "ordered_list_open":
            start = 1
            if tok.attrs:
                if isinstance(tok.attrs, dict):
                    val = tok.attrs.get("start")
                    if val is not None:
                        try:
                            start = int(val)
                        except (TypeError, ValueError):
                            start = 1
                else:
                    for key, val in tok.attrs:
                        if key == "start":
                            try:
                                start = int(val)
                            except (TypeError, ValueError):
                                start = 1
                            break
            list_stack.append({"type": "ordered", "index": start})
        elif t == "ordered_list_close":
            if list_stack:
                list_stack.pop()
            out.append("\n")
        elif t == "list_item_open":
            if list_stack:
                top = list_stack[-1]
                if top["type"] == "bullet":
                    pending_prefix = "\\- "
                else:
                    pending_prefix = f"{top['index']}\\."
                    top["index"] += 1
                    pending_prefix += " "
        elif t == "list_item_close":
            out.append("\n")
        elif t == "blockquote_open":
            blockquote_level += 1
        elif t == "blockquote_close":
            blockquote_level = max(0, blockquote_level - 1)
            out.append("\n")
        elif t == "table_open":
            # Telegram MarkdownV2 has no native table support; render as a monospaced
            # aligned table inside a fenced code block.
            if pending_prefix:
                out.append(apply_blockquote(pending_prefix.rstrip()))
                out.append("\n")
                pending_prefix = None

            rows: List[List[str]] = []
            row_is_header: List[bool] = []

            j = i + 1
            in_thead = False
            in_row = False
            current_row: List[str] = []
            current_row_header = False

            in_cell = False
            cell_parts: List[str] = []

            while j < len(tokens):
                tt = tokens[j].type
                if tt == "thead_open":
                    in_thead = True
                elif tt == "thead_close":
                    in_thead = False
                elif tt == "tr_open":
                    in_row = True
                    current_row = []
                    current_row_header = in_thead
                elif tt in {"th_open", "td_open"}:
                    in_cell = True
                    cell_parts = []
                elif tt == "inline" and in_cell:
                    cell_parts.append(
                        render_inline_table_plain(tokens[j].children or [])
                    )
                elif tt in {"th_close", "td_close"} and in_cell:
                    cell = " ".join(cell_parts).strip()
                    current_row.append(cell)
                    in_cell = False
                    cell_parts = []
                elif tt == "tr_close" and in_row:
                    rows.append(current_row)
                    row_is_header.append(bool(current_row_header))
                    in_row = False
                elif tt == "table_close":
                    break
                j += 1

            if rows:
                col_count = max((len(r) for r in rows), default=0)
                norm_rows: List[List[str]] = []
                for r in rows:
                    if len(r) < col_count:
                        r = r + [""] * (col_count - len(r))
                    norm_rows.append(r)

                widths: List[int] = []
                for c in range(col_count):
                    w = max((len(r[c]) for r in norm_rows), default=0)
                    widths.append(max(w, 3))

                def fmt_row(r: List[str]) -> str:
                    cells = [r[c].ljust(widths[c]) for c in range(col_count)]
                    return "| " + " | ".join(cells) + " |"

                def fmt_sep() -> str:
                    cells = ["-" * widths[c] for c in range(col_count)]
                    return "| " + " | ".join(cells) + " |"

                last_header_idx = -1
                for idx, is_h in enumerate(row_is_header):
                    if is_h:
                        last_header_idx = idx

                lines: List[str] = []
                for idx, r in enumerate(norm_rows):
                    lines.append(fmt_row(r))
                    if idx == last_header_idx:
                        lines.append(fmt_sep())

                table_text = "\n".join(lines).rstrip()
                out.append(f"```\n{escape_md_v2_code(table_text)}\n```")
                out.append("\n")

            # Skip consumed tokens through table_close.
            i = j + 1
            continue
        elif t in {"code_block", "fence"}:
            code = escape_md_v2_code(tok.content.rstrip("\n"))
            out.append(f"```\n{code}\n```")
            out.append("\n")
        elif t == "inline":
            rendered = render_inline(tok.children or [])
            if in_heading:
                rendered = f"*{render_inline_plain(tok.children or [])}*"
            if pending_prefix:
                rendered = pending_prefix + rendered
                pending_prefix = None
            rendered = apply_blockquote(rendered)
            out.append(rendered)
        else:
            if tok.content:
                out.append(escape_md_v2(tok.content))
        i += 1

    return "".join(out).rstrip()


class ClaudeMessageHandler:
    """
    Platform-agnostic handler for Claude interactions.

    Uses a tree-based message queue where:
    - New messages create a tree root
    - Replies become children of the message being replied to
    - Each node has state: PENDING, IN_PROGRESS, COMPLETED, ERROR
    - Per-tree queue ensures ordered processing
    """

    def __init__(
        self,
        platform: MessagingPlatform,
        cli_manager: SessionManagerInterface,
        session_store: SessionStore,
    ):
        self.platform = platform
        self.cli_manager = cli_manager
        self.session_store = session_store
        self.tree_queue = TreeQueueManager(
            queue_update_callback=self._update_queue_positions,
            node_started_callback=self._mark_node_processing,
        )

    async def handle_message(self, incoming: IncomingMessage) -> None:
        """
        Main entry point for handling an incoming message.

        Determines if this is a new conversation or reply,
        creates/extends the message tree, and queues for processing.
        """
        # Check for commands
        parts = (incoming.text or "").strip().split()
        cmd = parts[0] if parts else ""
        cmd_base = cmd.split("@", 1)[0] if cmd else ""

        # Record incoming message ID for best-effort UI clearing (/clear), even if
        # we later ignore this message (status/command/etc).
        try:
            if incoming.message_id is not None:
                kind = "command" if cmd_base.startswith("/") else "content"
                self.session_store.record_message_id(
                    incoming.platform,
                    incoming.chat_id,
                    str(incoming.message_id),
                    direction="in",
                    kind=kind,
                )
        except Exception as e:
            logger.debug(f"Failed to record incoming message_id: {e}")

        if cmd_base == "/clear":
            await self._handle_clear_command(incoming)
            return

        if cmd_base == "/stop":
            await self._handle_stop_command(incoming)
            return

        if cmd_base == "/stats":
            await self._handle_stats_command(incoming)
            return

        # Filter out status messages (our own messages)
        if any(
            incoming.text.startswith(p)
            for p in ["⏳", "💭", "🔧", "✅", "❌", "🚀", "🤖", "📋", "📊", "🔄"]
        ):
            return

        # Check if this is a reply to an existing node in a tree
        parent_node_id = None
        tree = None

        if incoming.is_reply() and incoming.reply_to_message_id:
            # Look up if the replied-to message is in any tree (could be a node or status message)
            reply_id = incoming.reply_to_message_id
            tree = self.tree_queue.get_tree_for_node(reply_id)
            if tree:
                # Resolve to actual node ID (handles status message replies)
                parent_node_id = self.tree_queue.resolve_parent_node_id(reply_id)
                if parent_node_id:
                    logger.info(f"Found tree for reply, parent node: {parent_node_id}")
                else:
                    logger.warning(
                        f"Reply to {incoming.reply_to_message_id} found tree but no valid parent node"
                    )
                    tree = None  # Treat as new conversation

        # Generate node ID
        node_id = incoming.message_id

        # Send initial status message
        status_text = self._get_initial_status(tree, parent_node_id)
        status_msg_id = await self.platform.queue_send_message(
            incoming.chat_id,
            status_text,
            reply_to=incoming.message_id,
            fire_and_forget=False,
        )
        try:
            if status_msg_id:
                self.session_store.record_message_id(
                    incoming.platform,
                    incoming.chat_id,
                    str(status_msg_id),
                    direction="out",
                    kind="status",
                )
        except Exception as e:
            logger.debug(f"Failed to record status message_id: {e}")

        # Create or extend tree
        if parent_node_id and tree and status_msg_id:
            # Reply to existing node - add as child
            tree, node = await self.tree_queue.add_to_tree(
                parent_node_id=parent_node_id,
                node_id=node_id,
                incoming=incoming,
                status_message_id=status_msg_id,
            )
            # Register status message as a node too for reply chains
            self.tree_queue.register_node(status_msg_id, tree.root_id)
            self.session_store.register_node(status_msg_id, tree.root_id)
            self.session_store.register_node(node_id, tree.root_id)
        elif status_msg_id:
            # New conversation - create new tree
            tree = await self.tree_queue.create_tree(
                node_id=node_id,
                incoming=incoming,
                status_message_id=status_msg_id,
            )
            # Register status message
            self.tree_queue.register_node(status_msg_id, tree.root_id)
            self.session_store.register_node(node_id, tree.root_id)
            self.session_store.register_node(status_msg_id, tree.root_id)

        # Persist tree
        if tree:
            self.session_store.save_tree(tree.root_id, tree.to_dict())

        # Enqueue for processing
        was_queued = await self.tree_queue.enqueue(
            node_id=node_id,
            processor=self._process_node,
        )

        if was_queued and status_msg_id:
            # Update status to show queue position
            queue_size = self.tree_queue.get_queue_size(node_id)
            await self.platform.queue_edit_message(
                incoming.chat_id,
                status_msg_id,
                format_status("📋", "Queued", f"(position {queue_size}) - waiting..."),
                parse_mode="MarkdownV2",
            )

    async def _update_queue_positions(self, tree: MessageTree) -> None:
        """Refresh queued status messages after a dequeue."""
        try:
            queued_ids = await tree.get_queue_snapshot()
        except Exception as e:
            logger.warning(f"Failed to read queue snapshot: {e}")
            return

        if not queued_ids:
            return

        position = 0
        for node_id in queued_ids:
            node = tree.get_node(node_id)
            if not node or node.state != MessageState.PENDING:
                continue
            position += 1
            self.platform.fire_and_forget(
                self.platform.queue_edit_message(
                    node.incoming.chat_id,
                    node.status_message_id,
                    format_status(
                        "📋", "Queued", f"(position {position}) - waiting..."
                    ),
                    parse_mode="MarkdownV2",
                )
            )

    async def _mark_node_processing(self, tree: MessageTree, node_id: str) -> None:
        """Update the dequeued node's status to processing immediately."""
        node = tree.get_node(node_id)
        if not node or node.state == MessageState.ERROR:
            return
        self.platform.fire_and_forget(
            self.platform.queue_edit_message(
                node.incoming.chat_id,
                node.status_message_id,
                format_status("🔄", "Processing..."),
                parse_mode="MarkdownV2",
            )
        )

    async def _process_node(
        self,
        node_id: str,
        node: MessageNode,
    ) -> None:
        """Core task processor - handles a single Claude CLI interaction."""
        incoming = node.incoming
        status_msg_id = node.status_message_id
        chat_id = incoming.chat_id

        # Update node state to IN_PROGRESS
        tree = self.tree_queue.get_tree_for_node(node_id)
        if tree:
            await tree.update_state(node_id, MessageState.IN_PROGRESS)

        # Components for structured display
        components = {
            "thinking": [],
            "tools": [],
            "subagents": [],
            "content": [],
            "errors": [],
        }

        last_ui_update = 0.0
        last_displayed_text = None
        captured_session_id = None
        temp_session_id = None

        # Get parent session ID for forking (if child node)
        parent_session_id = None
        if tree and node.parent_id:
            parent_session_id = tree.get_parent_session_id(node_id)
            if parent_session_id:
                logger.info(f"Will fork from parent session: {parent_session_id}")

        async def update_ui(status: Optional[str] = None, force: bool = False) -> None:
            nonlocal last_ui_update, last_displayed_text
            now = time.time()

            # Small 1s debounce for UI sanity - we still want to avoid
            # spamming the queue with too many intermediate states
            if not force and now - last_ui_update < 1.0:
                return

            last_ui_update = now
            display = self._build_message(components, status)
            if display and display != last_displayed_text:
                last_displayed_text = display
                await self.platform.queue_edit_message(
                    chat_id, status_msg_id, display, parse_mode="MarkdownV2"
                )

        try:
            # Get or create CLI session
            try:
                (
                    cli_session,
                    session_or_temp_id,
                    is_new,
                ) = await self.cli_manager.get_or_create_session(
                    session_id=None  # Always create a fresh session per node
                )
                if is_new:
                    temp_session_id = session_or_temp_id
                else:
                    captured_session_id = session_or_temp_id
            except RuntimeError as e:
                components["errors"].append(str(e))
                await update_ui(
                    format_status("⏳", "Session limit reached"), force=True
                )
                if tree:
                    await tree.update_state(
                        node_id, MessageState.ERROR, error_message=str(e)
                    )
                return

            # Process CLI events
            logger.info(f"HANDLER: Starting CLI task processing for node {node_id}")
            event_count = 0
            async for event_data in cli_session.start_task(
                incoming.text,
                session_id=parent_session_id,
                fork_session=bool(parent_session_id),
            ):
                if not isinstance(event_data, dict):
                    logger.warning(
                        f"HANDLER: Non-dict event received: {type(event_data)}"
                    )
                    continue
                event_count += 1
                if event_count % 10 == 0:
                    logger.debug(f"HANDLER: Processed {event_count} events so far")

                # Handle session_info event
                if event_data.get("type") == "session_info":
                    real_session_id = event_data.get("session_id")
                    if real_session_id and temp_session_id:
                        await self.cli_manager.register_real_session_id(
                            temp_session_id, real_session_id
                        )
                        captured_session_id = real_session_id
                        temp_session_id = None
                        # Persist session_id early so replies can fork even if a task
                        # is stopped before completion.
                        if tree and captured_session_id:
                            await tree.update_state(
                                node_id,
                                MessageState.IN_PROGRESS,
                                session_id=captured_session_id,
                            )
                            self.session_store.save_tree(tree.root_id, tree.to_dict())
                    continue

                parsed_list = parse_cli_event(event_data)
                logger.debug(f"HANDLER: Parsed {len(parsed_list)} events from CLI")

                for parsed in parsed_list:
                    if parsed["type"] == "thinking":
                        components["thinking"].append(parsed["text"])
                        await update_ui(format_status("🧠", "Claude is thinking..."))

                    elif parsed["type"] == "content":
                        if parsed.get("text"):
                            components["content"].append(parsed["text"])
                        await update_ui(format_status("🧠", "Claude is working..."))

                    elif parsed["type"] == "tool_start":
                        names = [t.get("name") for t in parsed.get("tools", [])]
                        components["tools"].extend(names)
                        await update_ui(format_status("⏳", "Executing tools..."))

                    elif parsed["type"] == "subagent_start":
                        tasks = parsed.get("tasks", [])
                        components["subagents"].extend(tasks)
                        await update_ui(format_status("🤖", "Subagent working..."))

                    elif parsed["type"] == "complete":
                        if not any(components.values()):
                            components["content"].append("Done.")
                        logger.info("HANDLER: Task complete, updating UI")
                        await update_ui(format_status("✅", "Complete"), force=True)

                        # Update node state and session
                        if tree and captured_session_id:
                            await tree.update_state(
                                node_id,
                                MessageState.COMPLETED,
                                session_id=captured_session_id,
                            )
                            self.session_store.save_tree(tree.root_id, tree.to_dict())

                    elif parsed["type"] == "error":
                        error_msg = parsed.get("message", "Unknown error")
                        logger.error(
                            f"HANDLER: Error event received: {error_msg[:200]}"
                        )
                        components["errors"].append(error_msg)
                        logger.info("HANDLER: Updating UI with error status")
                        await update_ui(format_status("❌", "Error"), force=True)
                        if tree:
                            await self._propagate_error_to_children(
                                node_id, error_msg, "Parent task failed"
                            )

        except asyncio.CancelledError:
            logger.warning(f"HANDLER: Task cancelled for node {node_id}")
            cancel_reason = None
            if isinstance(node.context, dict):
                cancel_reason = node.context.get("cancel_reason")

            if cancel_reason == "stop":
                await update_ui(format_status("⏹", "Stopped."), force=True)
            else:
                components["errors"].append("Task was cancelled")
                await update_ui(format_status("❌", "Cancelled"), force=True)

            # Do not propagate cancellation to children; a reply-scoped "/stop"
            # should only stop the targeted task.
            if tree:
                await tree.update_state(
                    node_id, MessageState.ERROR, error_message="Cancelled by user"
                )
        except Exception as e:
            logger.error(
                f"HANDLER: Task failed with exception: {type(e).__name__}: {e}"
            )
            error_msg = str(e)[:200]
            components["errors"].append(error_msg)
            await update_ui(format_status("💥", "Task Failed"), force=True)
            if tree:
                await self._propagate_error_to_children(
                    node_id, error_msg, "Parent task failed"
                )
        finally:
            logger.info(
                f"HANDLER: _process_node completed for node {node_id}, errors={len(components['errors'])}"
            )
            # Free the session-manager slot. Session IDs are persisted in the tree and
            # can be resumed later by ID; we don't need to keep a CLISession instance
            # around after this node completes.
            try:
                if captured_session_id:
                    await self.cli_manager.remove_session(captured_session_id)
                elif temp_session_id:
                    await self.cli_manager.remove_session(temp_session_id)
            except Exception as e:
                logger.debug(f"Failed to remove session for node {node_id}: {e}")

    async def _propagate_error_to_children(
        self,
        node_id: str,
        error_msg: str,
        child_status_text: str,
    ) -> None:
        """Mark node as error and propagate to pending children with UI updates."""
        affected = await self.tree_queue.mark_node_error(
            node_id, error_msg, propagate_to_children=True
        )
        # Update status messages for all affected children (skip first = current node)
        for child in affected[1:]:
            self.platform.fire_and_forget(
                self.platform.queue_edit_message(
                    child.incoming.chat_id,
                    child.status_message_id,
                    format_status("❌", "Cancelled:", child_status_text),
                    parse_mode="MarkdownV2",
                )
            )

    def _build_message(
        self,
        components: dict,
        status: Optional[str] = None,
    ) -> str:
        """
        Build unified message with specific order.
        Handles truncation while preserving markdown structure (closing code blocks).
        """
        lines = []

        # 1. Thinking
        if components["thinking"]:
            thinking_text = "".join(components["thinking"])
            # Truncate thinking if too long, it's usually less critical than final content
            if len(thinking_text) > 1000:
                thinking_text = "..." + thinking_text[-995:]

            lines.append(
                f"💭 {mdv2_bold('Thinking:')}\n```\n{escape_md_v2_code(thinking_text)}\n```"
            )

        # 2. Tools
        if components["tools"]:
            unique_tools = []
            seen = set()
            for t in components["tools"]:
                if t and t not in seen:
                    unique_tools.append(str(t))
                    seen.add(t)
            if unique_tools:
                lines.append(
                    f"🛠 {mdv2_bold('Tools:')} {mdv2_code_inline(', '.join(unique_tools))}"
                )

        # 3. Subagents
        if components["subagents"]:
            for task in components["subagents"]:
                lines.append(f"🤖 {mdv2_bold('Subagent:')} {mdv2_code_inline(task)}")

        # 4. Content
        if components["content"]:
            lines.append(render_markdown_to_mdv2("".join(components["content"])))

        # 5. Errors
        if components["errors"]:
            for err in components["errors"]:
                lines.append(f"⚠️ {mdv2_bold('Error:')} {mdv2_code_inline(err)}")

        if not any(lines) and not status:
            return format_status("⏳", "Claude is working...")

        # Telegram character limit is 4096. We leave buffer for status updates.
        LIMIT = 3900

        # Filter out empty lines first for a clean join
        lines = [l for l in lines if l]

        main_text = "\n".join(lines)
        status_text = f"\n\n{status}" if status else ""

        if len(main_text) + len(status_text) <= LIMIT:
            return (
                main_text + status_text
                if main_text + status_text
                else format_status("⏳", "Claude is working...")
            )

        # If too long, truncate the start of the content (keep the end)
        available_limit = LIMIT - len(status_text) - 20  # 20 for truncation marker
        raw_truncated = main_text[-available_limit:].lstrip()

        # Check for unbalanced code blocks
        prefix = escape_md_v2("... (truncated)\n")
        if raw_truncated.count("```") % 2 != 0:
            prefix += "```\n"

        truncated_main = prefix + raw_truncated

        return truncated_main + status_text

    def _get_initial_status(
        self,
        tree: Optional[object],
        parent_node_id: Optional[str],
    ) -> str:
        """Get initial status message text."""
        if tree and parent_node_id:
            # Reply to existing tree
            if self.tree_queue.is_node_tree_busy(parent_node_id):
                queue_size = self.tree_queue.get_queue_size(parent_node_id) + 1
                return format_status(
                    "📋", "Queued", f"(position {queue_size}) - waiting..."
                )
            return format_status("🔄", "Continuing conversation...")

        # New conversation
        stats = self.cli_manager.get_stats()
        if stats["active_sessions"] >= stats["max_sessions"]:
            return format_status(
                "⏳",
                "Waiting for slot...",
                f"({stats['active_sessions']}/{stats['max_sessions']})",
            )
        return format_status("⏳", "Launching new Claude CLI instance...")

    async def stop_all_tasks(self) -> int:
        """
        Stop all pending and in-progress tasks.

        Order of operations:
        1. Cancel tree queue tasks (uses internal locking)
        2. Stop CLI sessions
        3. Update UI for all affected nodes
        """
        # 1. Cancel tree queue tasks using the public async method
        logger.info("Cancelling tree queue tasks...")
        cancelled_nodes = await self.tree_queue.cancel_all()
        logger.info(f"Cancelled {len(cancelled_nodes)} nodes")

        # 2. Stop CLI sessions - this kills subprocesses and ensures everything is dead
        logger.info("Stopping all CLI sessions...")
        await self.cli_manager.stop_all()

        # 3. Update UI and persist state for all cancelled nodes
        for node in cancelled_nodes:
            self.platform.fire_and_forget(
                self.platform.queue_edit_message(
                    node.incoming.chat_id,
                    node.status_message_id,
                    format_status("⏹", "Stopped."),
                    parse_mode="MarkdownV2",
                )
            )

            # Persist tree state
            tree = self.tree_queue.get_tree_for_node(node.node_id)
            if tree:
                self.session_store.save_tree(tree.root_id, tree.to_dict())

        return len(cancelled_nodes)

    async def stop_task(self, node_id: str) -> int:
        """
        Stop a single queued or in-progress task node.

        Used when the user replies "/stop" to a specific status/user message.
        """
        tree = self.tree_queue.get_tree_for_node(node_id)
        if tree:
            node = tree.get_node(node_id)
            if node and node.state not in (MessageState.COMPLETED, MessageState.ERROR):
                # Used by _process_node cancellation path to render "Stopped."
                node.context = {"cancel_reason": "stop"}

        cancelled_nodes = await self.tree_queue.cancel_node(node_id)

        for node in cancelled_nodes:
            self.platform.fire_and_forget(
                self.platform.queue_edit_message(
                    node.incoming.chat_id,
                    node.status_message_id,
                    format_status("⏹", "Stopped."),
                    parse_mode="MarkdownV2",
                )
            )

            tree = self.tree_queue.get_tree_for_node(node.node_id)
            if tree:
                self.session_store.save_tree(tree.root_id, tree.to_dict())

        return len(cancelled_nodes)

    async def _handle_stop_command(self, incoming: IncomingMessage) -> None:
        """Handle /stop command from messaging platform."""
        # Reply-scoped stop: reply "/stop" to stop only that task.
        if incoming.is_reply() and incoming.reply_to_message_id:
            reply_id = incoming.reply_to_message_id
            tree = self.tree_queue.get_tree_for_node(reply_id)
            node_id = self.tree_queue.resolve_parent_node_id(reply_id) if tree else None

            if not node_id:
                msg_id = await self.platform.queue_send_message(
                    incoming.chat_id,
                    format_status("⏹", "Stopped.", "Nothing to stop for that message."),
                    fire_and_forget=False,
                )
                try:
                    if msg_id:
                        self.session_store.record_message_id(
                            incoming.platform,
                            incoming.chat_id,
                            str(msg_id),
                            direction="out",
                            kind="command",
                        )
                except Exception:
                    pass
                return

            count = await self.stop_task(node_id)
            noun = "request" if count == 1 else "requests"
            msg_id = await self.platform.queue_send_message(
                incoming.chat_id,
                format_status("⏹", "Stopped.", f"Cancelled {count} {noun}."),
                fire_and_forget=False,
            )
            try:
                if msg_id:
                    self.session_store.record_message_id(
                        incoming.platform,
                        incoming.chat_id,
                        str(msg_id),
                        direction="out",
                        kind="command",
                    )
            except Exception:
                pass
            return

        # Global stop: legacy behavior (stop everything)
        count = await self.stop_all_tasks()
        msg_id = await self.platform.queue_send_message(
            incoming.chat_id,
            format_status(
                "⏹", "Stopped.", f"Cancelled {count} pending or active requests."
            ),
            fire_and_forget=False,
        )
        try:
            if msg_id:
                self.session_store.record_message_id(
                    incoming.platform,
                    incoming.chat_id,
                    str(msg_id),
                    direction="out",
                    kind="command",
                )
        except Exception:
            pass

    async def _handle_stats_command(self, incoming: IncomingMessage) -> None:
        """Handle /stats command."""
        stats = self.cli_manager.get_stats()
        tree_count = self.tree_queue.get_tree_count()
        msg_id = await self.platform.queue_send_message(
            incoming.chat_id,
            "📊 "
            + mdv2_bold("Stats")
            + "\n"
            + escape_md_v2(f"• Active CLI: {stats['active_sessions']}")
            + "\n"
            + escape_md_v2(f"• Max CLI: {stats['max_sessions']}")
            + "\n"
            + escape_md_v2(f"• Message Trees: {tree_count}"),
            fire_and_forget=False,
        )
        try:
            if msg_id:
                self.session_store.record_message_id(
                    incoming.platform,
                    incoming.chat_id,
                    str(msg_id),
                    direction="out",
                    kind="command",
                )
        except Exception:
            pass

    async def _handle_clear_command(self, incoming: IncomingMessage) -> None:
        """
        Handle /clear global command.

        Order:
        1. Stop all pending/in-progress tasks.
        2. Best-effort delete tracked chat messages for this chat.
        3. Clear sessions.json (entire store) and reset in-memory queue state.
        """
        # 1) Stop tasks first (ensures no more work is running).
        await self.stop_all_tasks()

        # 2) Clear chat: best-effort delete messages we can identify.
        msg_ids: set[str] = set()

        # Add any recorded message IDs for this chat (commands, command replies, etc).
        try:
            for mid in self.session_store.get_message_ids_for_chat(
                incoming.platform, incoming.chat_id
            ):
                if mid is not None:
                    msg_ids.add(str(mid))
        except Exception as e:
            logger.debug(f"Failed to read message log for /clear: {e}")

        try:
            data = self.tree_queue.to_dict()
            trees = data.get("trees", {})
            for tree_data in trees.values():
                nodes = tree_data.get("nodes", {})
                for node_data in nodes.values():
                    inc = node_data.get("incoming", {}) or {}
                    if str(inc.get("platform")) != str(incoming.platform):
                        continue
                    if str(inc.get("chat_id")) != str(incoming.chat_id):
                        continue

                    mid = inc.get("message_id")
                    if mid is not None:
                        msg_ids.add(str(mid))

                    sid = node_data.get("status_message_id")
                    if sid is not None:
                        msg_ids.add(str(sid))
        except Exception as e:
            logger.warning(f"Failed to gather messages for /clear: {e}")

        # Also delete the command message itself.
        if incoming.message_id is not None:
            msg_ids.add(str(incoming.message_id))

        def _as_int(s: str) -> int | None:
            try:
                return int(str(s))
            except Exception:
                return None

        numeric: list[tuple[int, str]] = []
        non_numeric: list[str] = []
        for mid in msg_ids:
            n = _as_int(mid)
            if n is None:
                non_numeric.append(mid)
            else:
                numeric.append((n, mid))

        numeric.sort(reverse=True)
        ordered = [mid for _, mid in numeric] + non_numeric

        # If platform supports batch deletes, prefer it.
        batch_fn = getattr(self.platform, "queue_delete_messages", None)
        if callable(batch_fn):
            try:
                # Telegram supports up to 100 per request.
                CHUNK = 100
                for i in range(0, len(ordered), CHUNK):
                    chunk = ordered[i : i + CHUNK]
                    await batch_fn(incoming.chat_id, chunk, fire_and_forget=False)
            except Exception as e:
                logger.debug(f"/clear batch delete failed: {type(e).__name__}: {e}")
        else:
            for mid in ordered:
                try:
                    await self.platform.queue_delete_message(
                        incoming.chat_id,
                        mid,
                        fire_and_forget=False,
                    )
                except Exception as e:
                    # Deleting is best-effort; platform adapters also treat common cases as no-op.
                    logger.debug(
                        f"/clear delete failed for msg {mid}: {type(e).__name__}: {e}"
                    )

        # 3) Clear persistent state and reset in-memory queue/tree state.
        try:
            self.session_store.clear_all()
        except Exception as e:
            logger.warning(f"Failed to clear session store: {e}")

        self.tree_queue = TreeQueueManager(
            queue_update_callback=self._update_queue_positions,
            node_started_callback=self._mark_node_processing,
        )
