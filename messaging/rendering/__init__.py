"""Markdown rendering utilities for messaging platforms."""

from .discord_markdown import (
    discord_bold,
    discord_code_inline,
    escape_discord,
    escape_discord_code,
    format_status_discord,
    render_markdown_to_discord,
)
from .discord_markdown import (
    format_status as format_status_discord_fn,
)
from .telegram_markdown import (
    escape_md_v2,
    escape_md_v2_code,
    escape_md_v2_link_url,
    mdv2_bold,
    mdv2_code_inline,
    render_markdown_to_mdv2,
)
from .telegram_markdown import (
    format_status as format_status_telegram_fn,
)

__all__ = [
    "discord_bold",
    "discord_code_inline",
    "escape_discord",
    "escape_discord_code",
    "escape_md_v2",
    "escape_md_v2_code",
    "escape_md_v2_link_url",
    "format_status_discord",
    "format_status_discord_fn",
    "format_status_telegram_fn",
    "mdv2_bold",
    "mdv2_code_inline",
    "render_markdown_to_discord",
    "render_markdown_to_mdv2",
]
