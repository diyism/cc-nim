# Local Live Smoke Tests

`smoke/` is for live/process/service checks only. Hermetic feature contracts
belong under `tests/` and run with plain `uv run pytest`.

## Safe Default Run

```powershell
$env:FCC_LIVE_SMOKE = "1"
uv run pytest smoke -n 0 -m live -s --tb=short
```

`-n 0` is recommended because the normal project pytest config enables xdist.
The smoke suite can run with workers, but one process gives clearer logs when a
real provider, bot, or local model server fails.

## Targets

Default targets do not require bot tokens or voice backends:

| Target | What it checks | Required environment |
| --- | --- | --- |
| `api` | live uvicorn routes, probes, token count, optimizations, `/stop` fallback | none |
| `auth` | Anthropic auth header variants on a live server | none; test sets an isolated token |
| `cli` | `fcc-init`, `free-claude-code`, optional Claude CLI prompt | `claude` and provider config only for the prompt check |
| `clients` | VS Code and JetBrains-shaped requests | none |
| `providers` | configured provider model streams | provider keys or local provider URLs |
| `tools` | configured model emits live tool use | tool-capable configured provider |
| `rate_limit` | client disconnect does not crash a provider stream | configured provider |
| `lmstudio` | LM Studio `/models` endpoint is reachable | running LM Studio server |
| `llamacpp` | llama.cpp `/models` endpoint is reachable | running `llama-server` |

Side-effectful targets are opt-in:

| Target | What it checks | Required environment |
| --- | --- | --- |
| `telegram` | bot API getMe, send, edit, delete | `TELEGRAM_BOT_TOKEN` and chat/user ID |
| `discord` | channel access, send, edit, delete | `DISCORD_BOT_TOKEN` and channel ID |
| `voice` | configured transcription backend | `VOICE_NOTE_ENABLED=true` and `FCC_SMOKE_RUN_VOICE=1` |

Use `FCC_SMOKE_TARGETS=all` to include Telegram, Discord, and voice checks.

## Targeted Runs

```powershell
$env:FCC_LIVE_SMOKE = "1"
$env:FCC_SMOKE_TARGETS = "api,providers,tools"
uv run pytest smoke -n 0 -m live -s --tb=short
```

```powershell
$env:FCC_LIVE_SMOKE = "1"
$env:FCC_SMOKE_TARGETS = "telegram,discord,voice"
$env:FCC_SMOKE_RUN_VOICE = "1"
uv run pytest smoke -n 0 -m live -s --tb=short
```

## Environment

- `FCC_ENV_FILE`: optional explicit dotenv path. The app still uses its normal
  env-file precedence.
- `FCC_SMOKE_TARGETS`: comma-separated targets, or `all`.
- `FCC_SMOKE_PROVIDER_MATRIX`: comma-separated provider prefixes to test.
- `FCC_SMOKE_TIMEOUT_S`: per-request/subprocess timeout, default `45`.
- `FCC_SMOKE_CLAUDE_BIN`: Claude CLI executable name, default `claude`.
- `FCC_SMOKE_TELEGRAM_CHAT_ID`: Telegram chat/user ID for send/edit/delete.
- `FCC_SMOKE_DISCORD_CHANNEL_ID`: Discord channel ID for send/edit/delete.
- `FCC_SMOKE_INTERACTIVE=1`: enables manual inbound messaging checks.
- `FCC_SMOKE_RUN_VOICE=1`: allows the voice transcription backend to load/run.

## Feature Inventory

The public feature inventory lives in `smoke/features.py`. Each entry records
whether the feature is covered by hermetic pytest, live smoke, or both, plus the
owning tests and skip policy. The manifest intentionally excludes `claude-pick`.

## Results And Failure Classes

Smoke artifacts are written to `.smoke-results/` and ignored by git. Reports and
logs redact env values whose names contain `KEY`, `TOKEN`, `SECRET`, `WEBHOOK`,
or `AUTH`.

Report classifications:

- `missing_env`: a credential, opt-in flag, binary, channel, or model config is absent.
- `upstream_unavailable`: a real provider, bot API, or local model server is not reachable.
- `product_failure`: the app returned the wrong shape, crashed, or violated a contract.
- `harness_bug`: the smoke test made an invalid assumption.

`missing_env` and `upstream_unavailable` should skip. `product_failure` and
`harness_bug` should be fixed before relying on the smoke baseline.
