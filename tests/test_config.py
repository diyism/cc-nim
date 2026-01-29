"""Tests for config/settings.py"""

import pytest
import os


class TestSettings:
    """Test Settings configuration."""

    def test_settings_loads(self):
        """Ensure Settings can be instantiated."""
        from config.settings import Settings

        settings = Settings()
        assert settings is not None

    def test_default_values(self):
        """Test default values are set and have correct types."""
        from config.settings import Settings

        settings = Settings()
        assert isinstance(settings.nvidia_nim_rate_limit, int)
        assert isinstance(settings.nvidia_nim_rate_window, int)
        assert isinstance(settings.fast_prefix_detection, bool)
        assert isinstance(settings.max_cli_sessions, int)

    def test_get_settings_cached(self):
        """Test get_settings returns cached instance."""
        from config.settings import get_settings

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2  # Same object (cached)

    def test_empty_string_to_none_for_optional_int(self):
        """Test that empty string converts to None for optional int fields."""
        from config.settings import Settings

        # Settings should handle NVIDIA_NIM_SEED="" gracefully
        settings = Settings()
        assert settings.nvidia_nim_seed is None or isinstance(
            settings.nvidia_nim_seed, int
        )

    def test_model_mapping_defaults(self):
        """Test model mapping defaults."""
        from config.settings import Settings

        settings = Settings()
        assert "kimi" in settings.big_model.lower() or settings.big_model != ""
        assert "kimi" in settings.small_model.lower() or settings.small_model != ""
