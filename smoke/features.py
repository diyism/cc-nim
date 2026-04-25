"""Public feature inventory for pytest contracts and live smoke checks.

The inventory is intentionally explicit. README features and exposed public
surface area should have either hermetic pytest coverage, live smoke coverage,
or both. Private helpers are not listed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FeatureSource = Literal["readme", "public_surface"]
CoverageKind = Literal["pytest", "live_smoke", "both"]


@dataclass(frozen=True, slots=True)
class FeatureCoverage:
    feature_id: str
    title: str
    source: FeatureSource
    coverage: CoverageKind
    pytest_tests: tuple[str, ...]
    smoke_tests: tuple[str, ...]
    smoke_targets: tuple[str, ...]
    required_env: tuple[str, ...]
    skip_policy: str

    @property
    def has_pytest_coverage(self) -> bool:
        return self.coverage in {"pytest", "both"}

    @property
    def has_smoke_coverage(self) -> bool:
        return self.coverage in {"live_smoke", "both"}


README_FEATURES: tuple[str, ...] = (
    "zero_cost_provider_access",
    "drop_in_claude_code_replacement",
    "provider_matrix",
    "per_model_mapping",
    "thinking_token_support",
    "heuristic_tool_parser",
    "request_optimization",
    "smart_rate_limiting",
    "discord_telegram_bot",
    "subagent_control",
    "extensible_provider_platform_abcs",
    "optional_authentication",
    "vscode_extension",
    "intellij_extension",
    "voice_notes",
)


FEATURE_INVENTORY: tuple[FeatureCoverage, ...] = (
    FeatureCoverage(
        "zero_cost_provider_access",
        "Configured provider accepts a real prompt",
        "readme",
        "both",
        ("tests/api/test_dependencies.py", "tests/providers/test_open_router.py"),
        ("test_configured_provider_models_stream_successfully",),
        ("providers",),
        ("NVIDIA_NIM_API_KEY|OPENROUTER_API_KEY|DEEPSEEK_API_KEY|local provider",),
        "skip when no usable provider credentials or local provider endpoint exists",
    ),
    FeatureCoverage(
        "drop_in_claude_code_replacement",
        "Claude-compatible routes and CLI environment work",
        "readme",
        "both",
        ("tests/api/test_api.py", "tests/cli/test_cli.py"),
        (
            "test_probe_and_models_routes",
            "test_claude_cli_prompt_when_available",
            "test_vscode_and_jetbrains_shaped_requests",
        ),
        ("api", "cli", "clients"),
        ("FCC_SMOKE_CLAUDE_BIN", "configured provider for Claude CLI"),
        "skip Claude CLI path when binary or provider config is unavailable",
    ),
    FeatureCoverage(
        "provider_matrix",
        "All configured provider prefixes can be exercised",
        "readme",
        "both",
        ("tests/api/test_dependencies.py", "tests/providers/"),
        ("test_configured_provider_models_stream_successfully",),
        ("providers",),
        ("MODEL", "MODEL_OPUS", "MODEL_SONNET", "MODEL_HAIKU"),
        "skip when no configured provider has usable credentials/base URL",
    ),
    FeatureCoverage(
        "per_model_mapping",
        "Opus, Sonnet, Haiku, and fallback mappings are visible",
        "readme",
        "both",
        ("tests/api/test_models_validators.py", "tests/config/test_config.py"),
        ("test_model_mapping_configuration_is_consistent",),
        ("providers",),
        ("MODEL", "MODEL_OPUS", "MODEL_SONNET", "MODEL_HAIKU"),
        "skip live provider execution when no provider config is usable",
    ),
    FeatureCoverage(
        "mixed_provider_mapping",
        "Model-specific overrides can route to different providers",
        "public_surface",
        "both",
        ("tests/config/test_config.py",),
        ("test_mixed_provider_model_mapping_when_configured",),
        ("providers",),
        ("MODEL", "MODEL_OPUS", "MODEL_SONNET", "MODEL_HAIKU"),
        "skip when fewer than two configured provider prefixes are present",
    ),
    FeatureCoverage(
        "thinking_token_support",
        "Thinking streams and suppression are contract-tested",
        "readme",
        "pytest",
        (
            "test_interleaved_thinking_text_blocks_are_valid",
            "test_split_think_tags_preserve_text_and_thinking",
            "test_enable_thinking_false_suppresses_reasoning_only",
        ),
        (),
        (),
        (),
        "hermetic contract coverage",
    ),
    FeatureCoverage(
        "heuristic_tool_parser",
        "Text tool calls become structured tool_use blocks",
        "readme",
        "both",
        (
            "tests/providers/test_parsers.py",
            "test_thinking_tool_text_and_transcript_order_contract",
        ),
        ("test_live_tool_use_when_configured_model_supports_tools",),
        ("tools",),
        ("configured tool-capable provider",),
        "skip live tool-use when no configured provider model is available",
    ),
    FeatureCoverage(
        "request_optimization",
        "Fast-path local optimizations respond without providers",
        "readme",
        "both",
        (
            "tests/api/test_optimization_handlers.py",
            "tests/api/test_routes_optimizations.py",
        ),
        ("test_optimization_fast_paths_do_not_need_provider",),
        ("api",),
        (),
        "always runnable once live server starts",
    ),
    FeatureCoverage(
        "smart_rate_limiting",
        "Provider limiter covers proactive throttling, 429 retry, and disconnects",
        "readme",
        "both",
        ("tests/providers/test_provider_rate_limit.py",),
        ("test_client_disconnect_mid_stream_does_not_crash_server",),
        ("rate_limit", "providers"),
        ("configured provider",),
        "skip live disconnect path when no configured provider model is available",
    ),
    FeatureCoverage(
        "discord_telegram_bot",
        "Messaging credentials, send/edit/delete, and transcript behavior",
        "readme",
        "both",
        (
            "tests/messaging/test_discord_platform.py",
            "tests/messaging/test_telegram.py",
        ),
        (
            "test_telegram_bot_api_permissions",
            "test_discord_bot_api_permissions",
            "test_interactive_inbound_messaging_requires_explicit_mode",
        ),
        ("telegram", "discord"),
        (
            "TELEGRAM_BOT_TOKEN",
            "ALLOWED_TELEGRAM_USER_ID|FCC_SMOKE_TELEGRAM_CHAT_ID",
            "DISCORD_BOT_TOKEN",
            "ALLOWED_DISCORD_CHANNELS|FCC_SMOKE_DISCORD_CHANNEL_ID",
        ),
        "skip when bot tokens/channels are absent; inbound checks require interactive mode",
    ),
    FeatureCoverage(
        "subagent_control",
        "Task tool calls do not run in the background",
        "readme",
        "pytest",
        (
            "tests/providers/test_subagent_interception.py",
            "test_thinking_tool_text_and_transcript_order_contract",
        ),
        (),
        (),
        (),
        "hermetic contract coverage",
    ),
    FeatureCoverage(
        "extensible_provider_platform_abcs",
        "Provider/platform registries expose expected built-ins",
        "readme",
        "pytest",
        ("test_provider_and_platform_registries_include_advertised_builtins",),
        (),
        (),
        (),
        "hermetic contract coverage",
    ),
    FeatureCoverage(
        "optional_authentication",
        "Anthropic-style auth headers are accepted and enforced",
        "readme",
        "both",
        ("tests/api/test_auth.py",),
        ("test_auth_token_is_enforced_for_all_supported_header_shapes",),
        ("auth",),
        ("ANTHROPIC_AUTH_TOKEN",),
        "live test starts an isolated server with its own token",
    ),
    FeatureCoverage(
        "vscode_extension",
        "VS Code-shaped beta requests work against the proxy",
        "readme",
        "live_smoke",
        (),
        ("test_vscode_and_jetbrains_shaped_requests",),
        ("clients",),
        (),
        "always runnable once live server starts",
    ),
    FeatureCoverage(
        "intellij_extension",
        "JetBrains/ACP-shaped environment requests work against the proxy",
        "readme",
        "live_smoke",
        (),
        ("test_vscode_and_jetbrains_shaped_requests",),
        ("clients",),
        (),
        "always runnable once live server starts",
    ),
    FeatureCoverage(
        "voice_notes",
        "Configured transcription backend can process an audio fixture",
        "readme",
        "both",
        (
            "tests/messaging/test_voice_handlers.py",
            "tests/messaging/test_transcription.py",
        ),
        ("test_voice_transcription_backend_when_explicitly_enabled",),
        ("voice",),
        ("VOICE_NOTE_ENABLED", "FCC_SMOKE_RUN_VOICE", "WHISPER_DEVICE"),
        "skip unless voice is explicitly enabled for local smoke",
    ),
    FeatureCoverage(
        "anthropic_api_routes",
        "Root, health, models, messages, count_tokens, and stop routes respond",
        "public_surface",
        "both",
        ("tests/api/test_api.py",),
        ("test_probe_and_models_routes", "test_stop_endpoint_reports_no_messaging"),
        ("api",),
        (),
        "always runnable once live server starts",
    ),
    FeatureCoverage(
        "probe_routes",
        "HEAD and OPTIONS compatibility probes return 204 and Allow headers",
        "public_surface",
        "both",
        ("tests/api/test_api.py::test_probe_endpoints_return_204_with_allow_headers",),
        ("test_probe_and_models_routes",),
        ("api",),
        (),
        "always runnable once live server starts",
    ),
    FeatureCoverage(
        "count_tokens_contract",
        "Token counting accepts text, thinking, tools, tool results, and images",
        "public_surface",
        "both",
        ("tests/api/test_request_utils.py",),
        ("test_count_tokens_accepts_thinking_tools_and_results",),
        ("api",),
        (),
        "always runnable once live server starts",
    ),
    FeatureCoverage(
        "provider_proxy_timeout_config",
        "Provider proxies and HTTP timeouts are passed into clients",
        "public_surface",
        "pytest",
        ("tests/api/test_dependencies.py",),
        (),
        (),
        (),
        "hermetic config coverage",
    ),
    FeatureCoverage(
        "lmstudio_endpoint",
        "Configured LM Studio endpoint exposes an OpenAI-compatible models route",
        "public_surface",
        "both",
        ("tests/providers/test_lmstudio.py",),
        ("test_lmstudio_models_endpoint_when_available",),
        ("lmstudio",),
        ("LM_STUDIO_BASE_URL",),
        "skip when the local LM Studio server is not reachable",
    ),
    FeatureCoverage(
        "llamacpp_endpoint",
        "Configured llama.cpp endpoint exposes an OpenAI-compatible models route",
        "public_surface",
        "both",
        ("tests/providers/test_llamacpp.py",),
        ("test_llamacpp_models_endpoint_when_available",),
        ("llamacpp",),
        ("LLAMACPP_BASE_URL",),
        "skip when the local llama.cpp server is not reachable",
    ),
    FeatureCoverage(
        "package_cli_entrypoints",
        "Installed package scripts scaffold config and start the server",
        "public_surface",
        "both",
        ("tests/cli/test_entrypoints.py",),
        (
            "test_fcc_init_scaffolds_user_config",
            "test_free_claude_code_entrypoint_starts_server",
        ),
        ("cli",),
        (),
        "always runnable once uv project dependencies are available",
    ),
    FeatureCoverage(
        "claude_cli_drop_in",
        "Claude CLI can send a prompt through the proxy when installed",
        "public_surface",
        "live_smoke",
        (),
        ("test_claude_cli_prompt_when_available",),
        ("cli",),
        ("FCC_SMOKE_CLAUDE_BIN", "configured provider"),
        "skip when Claude CLI or provider config is unavailable",
    ),
    FeatureCoverage(
        "messaging_commands",
        "Messaging /stop, /clear, and /stats commands use platform queues safely",
        "public_surface",
        "pytest",
        (
            "tests/messaging/test_handler.py",
            "tests/messaging/test_handler_integration.py",
        ),
        (),
        (),
        (),
        "hermetic messaging handler coverage",
    ),
    FeatureCoverage(
        "tree_threading",
        "Reply-based message trees support queueing, branching, and cancellation",
        "public_surface",
        "pytest",
        (
            "tests/messaging/test_tree_queue.py",
            "tests/messaging/test_tree_concurrency.py",
        ),
        (),
        (),
        (),
        "hermetic tree queue coverage",
    ),
    FeatureCoverage(
        "restart_restore",
        "Persisted tree state is restored after restart for reply routing",
        "public_surface",
        "pytest",
        ("tests/messaging/test_restart_reply_restore.py",),
        (),
        (),
        (),
        "hermetic persistence coverage",
    ),
    FeatureCoverage(
        "session_persistence",
        "SessionStore persists trees, node mappings, and message logs",
        "public_surface",
        "pytest",
        ("tests/messaging/test_session_store_edge_cases.py",),
        (),
        (),
        (),
        "hermetic persistence coverage",
    ),
    FeatureCoverage(
        "config_env_precedence",
        "Environment and dotenv precedence are deterministic",
        "public_surface",
        "pytest",
        ("tests/config/test_config.py",),
        (),
        (),
        (),
        "hermetic config coverage",
    ),
    FeatureCoverage(
        "removed_env_migration",
        "Removed NIM_ENABLE_THINKING env var fails fast with migration guidance",
        "public_surface",
        "pytest",
        ("tests/config/test_config.py",),
        (),
        (),
        (),
        "hermetic config coverage",
    ),
    FeatureCoverage(
        "streaming_error_mapping",
        "Provider and streaming errors map to Anthropic-compatible error shapes",
        "public_surface",
        "pytest",
        (
            "tests/providers/test_streaming_errors.py",
            "tests/providers/test_error_mapping.py",
        ),
        (),
        (),
        (),
        "hermetic provider coverage",
    ),
)


def feature_ids(*, source: FeatureSource | None = None) -> set[str]:
    """Return feature IDs covered by the inventory."""
    return {
        feature.feature_id
        for feature in FEATURE_INVENTORY
        if source is None or feature.source == source
    }


def smoke_feature_ids() -> set[str]:
    """Return feature IDs with at least one live smoke owner."""
    return {
        feature.feature_id
        for feature in FEATURE_INVENTORY
        if feature.has_smoke_coverage
    }
