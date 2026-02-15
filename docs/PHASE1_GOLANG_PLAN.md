# Phase 1: Go Proxy Implementation Plan

Port the HTTP proxy (API, optimization handlers, rate limiting, NIM provider, session store, CLI manager) to Go. **Telegram bot stays in Python** and will call this Go proxy.

---

## 1. Scope

### In Scope
| Component | Python Source | Go Target |
|-----------|---------------|-----------|
| HTTP server + routes | `api/app.py`, `api/routes.py` | `cmd/proxy/main.go`, `internal/http/` |
| Request/response models | `api/models/` | `internal/models/` |
| Optimization handlers | `api/optimization_handlers.py`, `api/detection.py` | `internal/optimization/` |
| Command utils | `api/command_utils.py` | `internal/optimization/command.go` |
| Token counting | `api/request_utils.py` | `internal/token/` (approx or tiktoken-go) |
| Rate limiter | `providers/rate_limit.py` | `internal/ratelimit/` |
| NIM request builder | `providers/nvidia_nim/request.py`, `utils/message_converter.py` | `internal/nim/request.go` |
| NIM client + streaming | `providers/nvidia_nim/client.py` | `internal/nim/client.go` |
| SSE builder | `providers/nvidia_nim/utils/sse_builder.py` | `internal/nim/sse.go` |
| Think parser | `providers/nvidia_nim/utils/think_parser.py` | `internal/nim/think_parser.go` |
| Heuristic tool parser | `providers/nvidia_nim/utils/heuristic_tool_parser.py` | `internal/nim/heuristic_tool.go` |
| Error mapping | `providers/nvidia_nim/errors.py` | `internal/nim/errors.go` |
| Session store | `messaging/session.py` | `internal/session/store.go` |
| CLI manager | `cli/manager.py`, `cli/session.py` | `internal/cli/manager.go` |
| Process registry | `cli/process_registry.py` | `internal/cli/registry.go` |
| Config | `config/settings.py`, `config/nim.py` | `internal/config/` |

### Out of Scope (Phase 1)
- Telegram bot (stays in Python)
- Message handler, tree queue, transcript (Telegram-specific)
- Messaging rate limiter (Telegram-specific)

---

## 2. Project Structure

```
free-claude-code/
├── cmd/
│   └── proxy/
│       └── main.go              # Entry point, load config, start server
├── internal/
│   ├── config/
│   │   ├── config.go            # Settings from env
│   │   └── nim.go               # NIM-specific settings
│   ├── http/
│   │   ├── server.go            # HTTP server setup
│   │   ├── routes.go            # Route registration
│   │   └── handlers.go          # Route handlers
│   ├── models/
│   │   ├── anthropic.go         # Request/response structs
│   │   └── openai.go            # OpenAI/NIM structs
│   ├── optimization/
│   │   ├── detection.go         # is_quota_check, is_title, etc.
│   │   ├── handlers.go         # try_optimizations, individual handlers
│   │   └── command.go          # extract_command_prefix, extract_filepaths
│   ├── token/
│   │   └── count.go             # Token estimation (approx or tiktoken-go)
│   ├── ratelimit/
│   │   └── limiter.go           # GlobalRateLimiter (sliding window)
│   ├── nim/
│   │   ├── client.go            # HTTP client, stream_response
│   │   ├── request.go           # build_request_body
│   │   ├── converter.go         # Anthropic -> OpenAI message format
│   │   ├── sse.go               # SSE event builder
│   │   ├── think_parser.go      # <think> tag parser
│   │   ├── heuristic_tool.go    # Heuristic tool call parser
│   │   └── errors.go            # Map OpenAI errors -> Anthropic
│   ├── session/
│   │   └── store.go             # JSON file store, trees, sessions
│   └── cli/
│       ├── manager.go           # CLISessionManager
│       ├── session.go           # CLISession (subprocess)
│       └── registry.go           # Process cleanup
├── go.mod
├── go.sum
└── Makefile
```

---

## 3. Implementation Order

### Milestone 1: Skeleton + Config + Optimization Fast-Path
**Goal:** Go server that returns optimized responses for quota, prefix, title, suggestion, filepath. No NIM yet.

| Step | Task | Files |
|------|------|-------|
| 1.1 | `go mod init`, project layout | `go.mod`, `cmd/proxy/main.go` |
| 1.2 | Config from env (viper or envconfig) | `internal/config/config.go`, `nim.go` |
| 1.3 | Request/response models (JSON tags) | `internal/models/anthropic.go` |
| 1.4 | Detection logic | `internal/optimization/detection.go` |
| 1.5 | Command utils (shlex equivalent) | `internal/optimization/command.go` |
| 1.6 | Optimization handlers | `internal/optimization/handlers.go` |
| 1.7 | HTTP routes: POST /v1/messages (optimization path only) | `internal/http/` |
| 1.8 | GET /, GET /health | `internal/http/handlers.go` |

**Verify:** `curl -X POST http://localhost:8082/v1/messages -d '{"model":"claude","messages":[{"role":"user","content":"quota check"}]}'` returns mock quota response.

---

### Milestone 2: Token Counting + Count Tokens Endpoint
**Goal:** Add POST /v1/messages/count_tokens.

| Step | Task | Files |
|------|------|-------|
| 2.1 | Token estimation: `len(text)/4` approximation or `tiktoken-go` | `internal/token/count.go` |
| 2.2 | Count tokens handler | `internal/http/handlers.go` |

**Verify:** `curl -X POST http://localhost:8082/v1/messages/count_tokens -d '{"model":"claude","messages":[{"role":"user","content":"hello"}]}'` returns `input_tokens`.

---

### Milestone 3: Rate Limiter
**Goal:** Add provider rate limiter before NIM calls.

| Step | Task | Files |
|------|------|-------|
| 3.1 | Sliding window rate limiter | `internal/ratelimit/limiter.go` |
| 3.2 | Reactive block on 429 | `internal/ratelimit/limiter.go` |
| 3.3 | Retry with backoff on 429 | `internal/ratelimit/limiter.go` |

**Verify:** Unit tests for limiter; integration test with mock NIM.

---

### Milestone 4: NIM Request Builder + Message Converter
**Goal:** Build OpenAI-format request body from Anthropic request.

| Step | Task | Files |
|------|------|-------|
| 4.1 | Anthropic -> OpenAI message converter | `internal/nim/converter.go` |
| 4.2 | Request body builder (max_tokens, temperature, tools, etc.) | `internal/nim/request.go` |
| 4.3 | NIM settings (from config) | `internal/config/nim.go` |

**Verify:** Unit tests for converter and request builder.

---

### Milestone 5: NIM Client + SSE Streaming
**Goal:** Stream NIM responses and convert to Anthropic SSE format.

| Step | Task | Files |
|------|------|-------|
| 5.1 | SSE event builder | `internal/nim/sse.go` |
| 5.2 | Think tag parser | `internal/nim/think_parser.go` |
| 5.3 | Heuristic tool parser | `internal/nim/heuristic_tool.go` |
| 5.4 | Error mapping | `internal/nim/errors.go` |
| 5.5 | NIM HTTP client (streaming) | `internal/nim/client.go` |
| 5.6 | Wire NIM into POST /v1/messages (non-optimized path) | `internal/http/handlers.go` |

**Verify:** Full flow: `claude` CLI connects to Go proxy, sends real request, receives streamed response.

---

### Milestone 6: Session Store
**Goal:** JSON file store for sessions and trees (for future Telegram integration).

| Step | Task | Files |
|------|------|-------|
| 6.1 | Session store (sessions, trees, node_to_tree) | `internal/session/store.go` |
| 6.2 | Debounced save | `internal/session/store.go` |
| 6.3 | Message log (optional, for /clear) | `internal/session/store.go` |

**Verify:** Unit tests; store survives restart.

---

### Milestone 7: CLI Manager + Process Registry
**Goal:** Spawn and manage Claude CLI subprocesses.

| Step | Task | Files |
|------|------|-------|
| 7.1 | Process registry (register, unregister, kill_all) | `internal/cli/registry.go` |
| 7.2 | CLISession (start_task, stop, env setup) | `internal/cli/session.go` |
| 7.3 | CLISessionManager (get_or_create, register_real_session_id) | `internal/cli/manager.go` |
| 7.4 | POST /stop handler | `internal/http/handlers.go` |
| 7.5 | Lifespan: init CLI manager, cleanup on shutdown | `cmd/proxy/main.go` |

**Verify:** Telegram bot (Python) can start CLI via Go proxy; POST /stop cancels tasks.

---

### Milestone 8: Polish
**Goal:** Production readiness.

| Step | Task |
|------|------|
| 8.1 | Graceful shutdown (timeout) |
| 8.2 | Logging (structured, e.g. slog) |
| 8.3 | Health check includes provider status |
| 8.4 | README for Go proxy |

---

## 4. API Contracts (JSON)

### Request: POST /v1/messages
```json
{
  "model": "claude-3-sonnet",
  "max_tokens": 4096,
  "messages": [{"role": "user", "content": "Hello"}],
  "system": "You are helpful.",
  "tools": [...],
  "tool_choice": "auto",
  "temperature": 1.0,
  "stop_sequences": null
}
```

### Response: Optimized (non-streaming JSON)
```json
{
  "id": "msg_xxx",
  "model": "claude-3-sonnet",
  "role": "assistant",
  "content": [{"type": "text", "text": "..."}],
  "stop_reason": "end_turn",
  "usage": {"input_tokens": 100, "output_tokens": 5}
}
```

### Response: Streaming (SSE)
- `event: message_start` → `data: {"type":"message_start",...}`
- `event: content_block_start` → `data: {"type":"content_block_start",...}`
- `event: content_block_delta` → ...
- `event: content_block_stop` → ...
- `event: message_delta` → ...
- `event: message_stop` → ...
- `[DONE]`

---

## 5. Go Dependencies

| Package | Purpose |
|---------|---------|
| `github.com/joho/godotenv` | Load .env |
| `github.com/kelseyhightower/envconfig` or `github.com/caarlos0/env` | Config from env |
| `github.com/sashabaranov/go-openai` | OpenAI client (NIM is OpenAI-compatible) |
| `github.com/google/uuid` | UUID generation |
| `github.com/pelletier/go-toml` or stdlib | Optional: config file |

---

## 6. Config Mapping (Env Vars)

| Python | Go |
|--------|-----|
| `NVIDIA_NIM_API_KEY` | `NVIDIA_NIM_API_KEY` |
| `MODEL` | `MODEL` |
| `NVIDIA_NIM_RATE_LIMIT` | `NVIDIA_NIM_RATE_LIMIT` |
| `NVIDIA_NIM_RATE_WINDOW` | `NVIDIA_NIM_RATE_WINDOW` |
| `FAST_PREFIX_DETECTION` | `FAST_PREFIX_DETECTION` |
| `ENABLE_NETWORK_PROBE_MOCK` | `ENABLE_NETWORK_PROBE_MOCK` |
| `ENABLE_TITLE_GENERATION_SKIP` | `ENABLE_TITLE_GENERATION_SKIP` |
| `ENABLE_SUGGESTION_MODE_SKIP` | `ENABLE_SUGGESTION_MODE_SKIP` |
| `ENABLE_FILEPATH_EXTRACTION_MOCK` | `ENABLE_FILEPATH_EXTRACTION_MOCK` |
| `CLAUDE_WORKSPACE` | `CLAUDE_WORKSPACE` |
| `ALLOWED_DIR` | `ALLOWED_DIR` |
| `MAX_CLI_SESSIONS` | `MAX_CLI_SESSIONS` |
| `HOST`, `PORT` | `HOST`, `PORT` |
| All `NVIDIA_NIM_*` | `NVIDIA_NIM_*` |

---

## 7. Token Counting Strategy

**Option A (recommended):** Use `len(text)/4` approximation. Fast, no deps. Claude uses cl100k; approximation is ~10–20% off for typical text.

**Option B:** Use `github.com/pkoukk/tiktoken-go` (community port). More accurate but adds dependency and binary size.

**Option C:** Call Python microservice for token count. Avoid for Phase 1 (adds complexity).

---

## 8. Testing Strategy

| Type | Approach |
|------|----------|
| Unit | `*_test.go` next to each package |
| Integration | Test server with mock NIM (httptest) |
| E2E | Run `claude` CLI against Go proxy; verify streaming |
| Parity | Compare Go proxy responses with Python proxy for same requests |

---

## 9. Acceptance Criteria

- [ ] Go proxy returns same optimized responses as Python for quota, prefix, title, suggestion, filepath
- [ ] Go proxy streams NIM responses correctly (thinking, text, tool_use)
- [ ] Claude CLI works with Go proxy (ANTHROPIC_BASE_URL=http://localhost:8082)
- [ ] POST /stop cancels running tasks
- [ ] Rate limiting: 40 req/60s enforced; 429 triggers backoff
- [ ] Session store persists and restores
- [ ] Graceful shutdown: CLI processes killed, no orphaned subprocesses
- [ ] Python Telegram bot can use Go proxy (no code changes to bot beyond base URL)

---

## 10. Estimated Effort

| Milestone | Effort |
|-----------|--------|
| M1: Skeleton + Config + Optimization | 2–3 days |
| M2: Token counting | 0.5 day |
| M3: Rate limiter | 1 day |
| M4: NIM request builder | 1–2 days |
| M5: NIM client + SSE | 2–3 days |
| M6: Session store | 1 day |
| M7: CLI manager | 1–2 days |
| M8: Polish | 1 day |
| **Total** | **~10–14 days** |
