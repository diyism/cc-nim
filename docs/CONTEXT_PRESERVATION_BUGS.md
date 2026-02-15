# Context Preservation Bugs for API Calls

Bugs in preserving interleaved **thinking**, **tool calls**, and **text** when converting between **Anthropic** format (API surface) and **NVIDIA NIM** (backend provider). NIM uses the OpenAI-compatible API format internally.

## Summary

| Bug | Location | Impact | Test |
|-----|----------|--------|------|
| 1. Assistant message interleaving lost | `message_converter._convert_assistant_message` | Thinking+text order flattened to [all thinking, all text, tool_calls] | `test_convert_assistant_interleaved_order_preserved` |
| 2. User message text/tool_result order reversed | `message_converter._convert_user_message` | User text emitted after tool results instead of before | `test_convert_user_message_text_before_tool_result_order` |
| 3. Response interleaved think tags collapsed | `response.convert_response` + `extract_think_content` | Multiple `<think>...</think>` blocks merged into one; text between them preserved but thinking blocks lose interleaving | `test_interleaved_think_tags_in_content_preserved` |

---

## Bug 1: Assistant Message Interleaving Lost

**File:** `providers/nvidia_nim/utils/message_converter.py`  
**Function:** `_convert_assistant_message`

**Current behavior:** Collects all `thinking` blocks into `reasoning_parts`, all `text` blocks into `text_parts`, all `tool_use` into `tool_calls`. Output order is always: `[all thinking] [all text] [tool_calls]`.

**Example:** Input blocks `[thinking, text, thinking, tool_use]`  
- **Expected:** Content string `<think>first</think>\n\nHere is the answer.\n\n<think>second</think>` with tool_calls at end  
- **Actual:** Content string `<think>first\nsecond</think>\n\nHere is the answer.` (all thinking merged first)

**API constraint:** NIM (OpenAI-compatible) format has `content: string` and `tool_calls: array`. Tool calls cannot be interleaved within content. We can only preserve thinking↔text order within the content string.

**Fix direction:** Iterate blocks in order; for each block, append to content string: if thinking → add `<think>...</think>`; if text → add text. Tool calls stay at end.

---

## Bug 2: User Message Text/Tool Result Order Reversed

**File:** `providers/nvidia_nim/utils/message_converter.py`  
**Function:** `_convert_user_message`

**Current behavior:** Emits `tool_result` blocks immediately to `result`, then appends user text at the end. Order becomes: `[tool, tool, ..., user]`.

**Example:** Input blocks `[text, tool_result]` (user says "Please use this result:", then provides tool output)  
- **Expected:** `[user, tool]`  
- **Actual:** `[tool, user]`

**Anthropic convention:** User typically provides context first, then tool results. Reversing can confuse models that expect user text before tool results.

**Fix direction:** Emit blocks in original order: text → user message, tool_result → tool message.

---

## Bug 3: Response Interleaved Think Tags Collapsed

**File:** `providers/nvidia_nim/response.py` + `providers/nvidia_nim/utils/think_parser.py`  
**Function:** `convert_response`, `extract_think_content`

**Current behavior:** `extract_think_content` uses `re.findall(r"<think>(.*?)</think>", text)` and joins all matches into one thinking string, then strips all tags from content. Remaining text is one block.

**Example:** Content `<think>first</think>middle<think>second</think>`  
- **Expected:** `[thinking("first"), text("middle"), thinking("second")]`  
- **Actual:** `[thinking("first\nsecond"), text("middle")]`

**Fix direction:** Parse content sequentially (e.g. iterate with `re.finditer` or use a stateful parser) and emit blocks in order: thinking, text, thinking, text, etc.

---

## Streaming Path

The **streaming** response path in `providers/nvidia_nim/client.py` uses `ThinkTagParser` and `HeuristicToolParser`, which yield chunks in order. Interleaving is preserved during streaming. The bugs above affect:

- **Request path:** Converting Anthropic messages → NIM (outbound API calls)
- **Non-streaming response path:** Converting NIM response → Anthropic format

---

## Failing Tests (Reproduction)

```bash
uv run pytest tests/test_converter.py::test_convert_assistant_interleaved_order_preserved -v
uv run pytest tests/test_converter.py::test_convert_user_message_text_before_tool_result_order -v
uv run pytest tests/test_response_conversion.py::TestConvertResponse::test_interleaved_think_tags_in_content_preserved -v
```

All three tests now pass after the fixes below.

## Fixes Applied

1. **Assistant interleaving:** `_convert_assistant_message` now iterates blocks in order and appends each thinking/text block to `content_parts` sequentially. Tool calls remain at the end (API constraint).

2. **User message order:** `_convert_user_message` now uses `flush_text()` before each tool_result so user text is emitted first when it precedes tool results.

3. **Response think tags:** Added `extract_think_content_interleaved()` that uses `re.finditer` to emit blocks in order. `convert_response` uses it when `reasoning_content` is absent.
