"""Backward-compatible re-export. Use messaging.rendering.discord_markdown for new code."""

from .rendering.discord_markdown import (
    _is_gfm_table_header_line,
    _normalize_gfm_tables,
    discord_bold,
    discord_code_inline,
    escape_discord,
    escape_discord_code,
    format_status,
    format_status_discord,
    render_markdown_to_discord,
)

__all__ = [
    "_is_gfm_table_header_line",
    "_normalize_gfm_tables",
    "discord_bold",
    "discord_code_inline",
    "escape_discord",
    "escape_discord_code",
    "format_status",
    "format_status_discord",
    "render_markdown_to_discord",
]
