# Resource Usage & Efficiency Optimization Plan

This document outlines opportunities to improve efficiency and resource usage across the Free Claude Code proxy. Each section identifies the current behavior, optimization opportunity, and suggested approach.

---

## 1. API Request Path Optimizations

### 1.1 Skip Token Counting for Optimized Responses
**Location:** `api/routes.py` (create_message)

**Current:** `get_token_count()` is only called when the request proceeds to streaming (after `try_optimizations` returns `None`). ✅ Already optimized.

**Status:** No change needed.

---

### 1.2 Detection Short-Circuit & Shared Text Extraction
**Location:** `api/detection.py`, `api/optimization_handlers.py`

**Current:** Each optimization handler may call `extract_text_from_content()` independently. For a single request, detection functions can extract text from the same content multiple times (e.g., `is_quota_check_request`, `is_prefix_detection_request` both inspect the first user message).

**Opportunity:** 
- Add a **single-pass detection** that extracts text once and runs all cheap checks (quota, title, suggestion, prefix, filepath) against it.
- Reorder handlers by **cheapest-first** (already done: quota → prefix → title → suggestion → filepath).
- Consider a **unified detection** function that returns a `(optimization_type, extracted_data)` tuple to avoid redundant parsing.

**Effort:** Low–Medium | **Impact:** Medium (reduces CPU per request on hot path)

---

### 1.3 Lazy Tiktoken Encoder
**Location:** `api/request_utils.py` (line 14)

**Current:** `ENCODER = tiktoken.get_encoding("cl100k_base")` is loaded at module import time. Tiktoken loading involves reading/parsing encoding files.

**Opportunity:** Use lazy initialization—only load the encoder on first `get_token_count()` call. For optimization-heavy workloads (quota, prefix, title, etc.), many requests never need token counting.

**Effort:** Low | **Impact:** Low–Medium (faster startup, less memory if optimizations dominate)

---

### 1.4 Fix Syntax Error in request_utils.py ✅ DONE
**Location:** `api/request_utils.py` line 89

**Current:** `except TypeError, ValueError:` — invalid Python 3 syntax.

**Fix:** `except (TypeError, ValueError):` — applied.

**Effort:** Trivial | **Impact:** Bug fix (code may not run correctly in edge cases)

---

## 2. Session Store & Persistence

### 2.1 Async-Friendly Session Store
**Location:** `messaging/session.py`

**Current:** Uses `threading.Lock` and synchronous file I/O (`open`, `json.load`, `json.dump`). All tree/session updates trigger debounced saves that block a thread.

**Opportunity:**
- Use `asyncio.Lock` and `aiofiles` (or `run_in_executor`) for non-blocking I/O.
- Keeps the event loop responsive during heavy save operations.
- Consider batching multiple dirty writes into a single flush.

**Effort:** Medium | **Impact:** Medium (better responsiveness under load)

---

### 2.2 Reduce Session Store Write Frequency
**Location:** `messaging/session.py` — `_schedule_save`, `record_message_id`, `save_tree`

**Current:** Debounce is 0.5s. Every `record_message_id` and `save_tree` can schedule a save. Under high message volume, this can still mean frequent disk writes.

**Opportunity:**
- Increase debounce to 1–2 seconds for tree/session updates.
- Add a max write interval (e.g., cap at 1 write per 2s even if dirty).
- For `record_message_id`, consider batching or skipping persistence for high-frequency status updates (if acceptable for `/clear` semantics).

**Effort:** Low | **Impact:** Low–Medium (fewer disk I/O operations)

---

## 3. Rate Limiters

### 3.1 Provider Rate Limiter — Sleep Outside Lock
**Location:** `providers/rate_limit.py` — `_acquire_proactive_slot`

**Current:** Already sleeps outside the lock. ✅ Good.

**Status:** No change needed.

---

### 3.2 Messaging Rate Limiter — Config from Settings
**Location:** `messaging/limiter.py` (lines 99–100)

**Current:** Reads `MESSAGING_RATE_LIMIT` and `MESSAGING_RATE_WINDOW` directly from `os.getenv()`, bypassing `config.settings`.

**Opportunity:** Inject these from `Settings` for consistency and testability. Reduces env reads and aligns with the rest of the app.

**Effort:** Low | **Impact:** Low (consistency, testability)

---

## 4. Messaging & Handler

### 4.1 Defer Message ID Recording
**Location:** `messaging/handler.py` — `handle_message`

**Current:** `record_message_id` is called for every incoming message, including commands and status echoes, before early returns.

**Opportunity:** Move `record_message_id` to after command/status filtering, or use a fire-and-forget pattern so the main path isn’t blocked by session store updates. The store already uses debounced saves, but the lock is still acquired synchronously.

**Effort:** Low | **Impact:** Low (slightly faster handler path)

---

### 4.2 Transcript Event Type Lookup
**Location:** `messaging/handler.py` — `TRANSCRIPT_EVENT_TYPES`

**Current:** Uses `frozenset` for O(1) membership. ✅ Good.

**Status:** No change needed.

---

## 5. Provider & Streaming

### 5.1 NIM Client — Reuse Parsers
**Location:** `providers/nvidia_nim/client.py` — `stream_response`

**Current:** Creates `ThinkTagParser()` and `HeuristicToolParser()` per request. These are lightweight.

**Opportunity:** If profiling shows allocation overhead, consider object pooling. Likely not necessary unless under extreme request rates.

**Effort:** Low | **Impact:** Low

---

### 5.2 SSE Builder Token Counting
**Location:** `providers/nvidia_nim/utils/sse_builder.py`

**Current:** Uses `ENCODER.encode()` for usage reporting. Shares tiktoken with `request_utils`.

**Opportunity:** Same lazy encoder as in 1.3. Ensure a single shared encoder instance.

**Effort:** Low | **Impact:** Low

---

## 6. CLI & Process Management

### 6.1 Idle Session Cleanup
**Location:** `cli/manager.py` — `_cleanup_idle_sessions_unlocked`

**Current:** Cleanup runs when hitting `max_sessions`. Sessions are removed when CLI exits.

**Opportunity:** Add a background task that periodically prunes idle sessions (e.g., no activity for N minutes) to free subprocesses and file descriptors earlier.

**Effort:** Medium | **Impact:** Medium (better resource reclaim under bursty usage)

---

### 6.2 Process Registry — Best-Effort Cleanup
**Location:** `cli/process_registry.py`, `server.py`

**Current:** `kill_all_best_effort()` runs in `finally` on shutdown. Good safety net.

**Status:** No change needed.

---

## 7. Application Lifespan

### 7.1 Lazy Messaging Initialization
**Location:** `api/app.py` — `lifespan`

**Current:** Messaging platform, session store, CLI manager, and tree queue are all initialized at startup, even when no Telegram messages are expected (e.g., CLI-only usage).

**Opportunity:** Defer messaging initialization until the first request that needs it (e.g., first `/stop` or first webhook hit). Reduces startup time and memory when running in CLI-only mode.

**Effort:** Medium | **Impact:** Medium (faster startup for CLI-only)

---

### 7.2 Tree Restoration
**Location:** `api/app.py` — `lifespan` (lines 101–121)

**Current:** Loads all trees and node mappings at startup, then runs `cleanup_stale_nodes()` and syncs back.

**Opportunity:** Run restoration in a background task so the server can accept requests sooner. Ensure handlers tolerate `tree_queue` not being fully restored for a short window.

**Effort:** Medium | **Impact:** Low–Medium (faster startup)

---

## 8. Configuration & Imports

### 8.1 Settings Loaded Twice at Startup
**Location:** `api/app.py` (lines 19–20, 46)

**Current:** `get_settings()` is called at module level and again in `lifespan`. `get_settings` is `@lru_cache()` so it’s cheap, but the pattern is redundant.

**Opportunity:** Use a single `settings = get_settings()` at module level and pass it where needed, or rely solely on `Depends(get_settings)` in lifespan.

**Effort:** Low | **Impact:** Low (cleaner code)

---

### 8.2 PTB Environment Variable
**Location:** `api/app.py` (line 7)

**Current:** `os.environ["PTB_TIMEDELTA"] = "1"` is set at import time. Required for python-telegram-bot.

**Status:** No change needed.

---

## 9. Summary: Recommended Priorities

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| P0 | Fix `except TypeError, ValueError` syntax | Trivial | Bug fix |
| P1 | Lazy tiktoken encoder | Low | Startup/memory |
| P1 | Single-pass detection / shared text extraction | Low–Med | CPU per request |
| P2 | Messaging limiter config from Settings | Low | Consistency |
| P2 | Session store debounce tuning | Low | Disk I/O |
| P3 | Async session store I/O | Medium | Responsiveness |
| P3 | Lazy messaging initialization | Medium | Startup (CLI-only) |
| P3 | Idle session cleanup background task | Medium | Resource reclaim |
| P4 | Tree restoration in background | Medium | Startup |
| P4 | Defer message ID recording | Low | Handler latency |

---

## 10. Implementation Order Suggestion

1. **Immediate:** Fix syntax error in `request_utils.py`.
2. **Quick wins:** Lazy tiktoken, single-pass detection, messaging limiter from Settings.
3. **Next:** Session store debounce, defer message ID recording.
4. **Larger refactors:** Async session store, lazy messaging init, idle session cleanup, background tree restoration.
