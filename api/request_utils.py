"""Request utility functions for API route handlers.

Contains token counting for API requests.
"""

import json
import logging
from typing import List, Optional, Union

import tiktoken

logger = logging.getLogger(__name__)
ENCODER = tiktoken.get_encoding("cl100k_base")

__all__ = ["get_token_count"]


def get_token_count(
    messages: List,
    system: Optional[Union[str, List]] = None,
    tools: Optional[List] = None,
) -> int:
    """Estimate token count for a request.

    Uses tiktoken cl100k_base encoding to estimate token usage.
    Includes system prompt, messages, tools, and per-message overhead.
    """
    total_tokens = 0

    if system:
        if isinstance(system, str):
            total_tokens += len(ENCODER.encode(system))
        elif isinstance(system, list):
            for block in system:
                text = (
                    getattr(block, "text", None)
                    if hasattr(block, "text")
                    else (block.get("text", "") if isinstance(block, dict) else "")
                )
                if text:
                    total_tokens += len(ENCODER.encode(text))
        total_tokens += 4  # System block formatting overhead

    for msg in messages:
        if isinstance(msg.content, str):
            total_tokens += len(ENCODER.encode(msg.content))
        elif isinstance(msg.content, list):
            for block in msg.content:
                b_type = getattr(block, "type", None) or (
                    block.get("type") if isinstance(block, dict) else None
                )

                if b_type == "text":
                    text = getattr(block, "text", "") or (
                        block.get("text", "") if isinstance(block, dict) else ""
                    )
                    total_tokens += len(ENCODER.encode(text))
                elif b_type == "thinking":
                    thinking = getattr(block, "thinking", "") or (
                        block.get("thinking", "") if isinstance(block, dict) else ""
                    )
                    total_tokens += len(ENCODER.encode(thinking))
                elif b_type == "tool_use":
                    name = getattr(block, "name", "") or (
                        block.get("name", "") if isinstance(block, dict) else ""
                    )
                    inp = getattr(block, "input", {}) or (
                        block.get("input", {}) if isinstance(block, dict) else {}
                    )
                    block_id = getattr(block, "id", "") or (
                        block.get("id", "") if isinstance(block, dict) else ""
                    )
                    total_tokens += len(ENCODER.encode(name))
                    total_tokens += len(ENCODER.encode(json.dumps(inp)))
                    total_tokens += len(ENCODER.encode(str(block_id)))
                    total_tokens += 15
                elif b_type == "image":
                    source = getattr(block, "source", None) or (
                        block.get("source", {}) if isinstance(block, dict) else {}
                    )
                    if isinstance(source, dict):
                        data = source.get("data") or source.get("base64") or ""
                        if data:
                            total_tokens += max(85, len(data) // 3000)
                        else:
                            total_tokens += 765
                    else:
                        total_tokens += 765
                elif b_type == "tool_result":
                    content = getattr(block, "content", "") or (
                        block.get("content", "") if isinstance(block, dict) else ""
                    )
                    tool_use_id = getattr(block, "tool_use_id", "") or (
                        block.get("tool_use_id", "") if isinstance(block, dict) else ""
                    )
                    if isinstance(content, str):
                        total_tokens += len(ENCODER.encode(content))
                    else:
                        total_tokens += len(ENCODER.encode(json.dumps(content)))
                    total_tokens += len(ENCODER.encode(str(tool_use_id)))
                    total_tokens += 8
                else:
                    try:
                        total_tokens += len(ENCODER.encode(json.dumps(block)))
                    except (TypeError, ValueError):
                        total_tokens += len(ENCODER.encode(str(block)))

    if tools:
        for tool in tools:
            tool_str = (
                tool.name + (tool.description or "") + json.dumps(tool.input_schema)
            )
            total_tokens += len(ENCODER.encode(tool_str))

    total_tokens += len(messages) * 4
    if tools:
        total_tokens += len(tools) * 5

    return max(1, total_tokens)
