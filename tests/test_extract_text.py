"""Tests for extract_text_from_content helper functions."""

import pytest
from unittest.mock import MagicMock

from api.request_utils import extract_text_from_content
from providers.logging_utils import _extract_text_from_content as logging_extract


class TestExtractTextFromContent:
    """Tests for api.request_utils.extract_text_from_content."""

    def test_string_content(self):
        """Return string content as-is."""
        assert extract_text_from_content("hello world") == "hello world"

    def test_empty_string(self):
        """Return empty string for empty string input."""
        assert extract_text_from_content("") == ""

    def test_list_single_block(self):
        """Extract text from a single content block."""
        block = MagicMock()
        block.text = "some text"
        assert extract_text_from_content([block]) == "some text"

    def test_list_multiple_blocks(self):
        """Concatenate text from multiple content blocks."""
        b1 = MagicMock()
        b1.text = "hello "
        b2 = MagicMock()
        b2.text = "world"
        assert extract_text_from_content([b1, b2]) == "hello world"

    def test_list_with_non_text_block(self):
        """Skip blocks without text attribute."""
        b1 = MagicMock()
        b1.text = "hello"
        b2 = MagicMock(spec=[])  # No attributes
        assert extract_text_from_content([b1, b2]) == "hello"

    def test_list_with_empty_text(self):
        """Skip blocks with empty text."""
        b1 = MagicMock()
        b1.text = ""
        b2 = MagicMock()
        b2.text = "world"
        assert extract_text_from_content([b1, b2]) == "world"

    def test_list_with_none_text(self):
        """Skip blocks with None text."""
        b1 = MagicMock()
        b1.text = None
        b2 = MagicMock()
        b2.text = "world"
        assert extract_text_from_content([b1, b2]) == "world"

    def test_empty_list(self):
        """Return empty string for empty list."""
        assert extract_text_from_content([]) == ""

    def test_non_string_non_list(self):
        """Return empty string for unexpected types."""
        assert extract_text_from_content(None) == ""
        assert extract_text_from_content(42) == ""

    def test_list_with_non_string_text_attr(self):
        """Skip blocks where text is not a string."""
        b1 = MagicMock()
        b1.text = 123  # Not a string
        b2 = MagicMock()
        b2.text = "valid"
        assert extract_text_from_content([b1, b2]) == "valid"


class TestLoggingExtractText:
    """Tests for providers.logging_utils._extract_text_from_content.

    Verifies the local helper in logging_utils behaves the same.
    """

    def test_string_content(self):
        assert logging_extract("hello") == "hello"

    def test_list_content(self):
        b = MagicMock()
        b.text = "test"
        assert logging_extract([b]) == "test"

    def test_empty_inputs(self):
        assert logging_extract("") == ""
        assert logging_extract([]) == ""
        assert logging_extract(None) == ""


# --- Parametrized Edge Case Tests ---


def _make_block(text_val):
    b = MagicMock()
    b.text = text_val
    return b


@pytest.mark.parametrize(
    "content,expected",
    [
        ("hello world", "hello world"),
        ("", ""),
        (None, ""),
        (42, ""),
        ([], ""),
        ("   ", "   "),
    ],
    ids=["string", "empty_str", "none", "int", "empty_list", "whitespace_only"],
)
def test_extract_text_scalar_and_empty_parametrized(content, expected):
    """Parametrized scalar and empty input handling."""
    assert extract_text_from_content(content) == expected


@pytest.mark.parametrize(
    "func",
    [extract_text_from_content, logging_extract],
    ids=["request_utils", "logging_utils"],
)
def test_both_extract_functions_whitespace_only(func):
    """Both extract functions handle whitespace-only string identically."""
    assert func("   ") == "   "


@pytest.mark.parametrize(
    "func",
    [extract_text_from_content, logging_extract],
    ids=["request_utils", "logging_utils"],
)
def test_both_extract_functions_unicode(func):
    """Both extract functions handle unicode content."""
    assert func("日本語テスト") == "日本語テスト"
