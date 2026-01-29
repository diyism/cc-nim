"""Tests for cli/ module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestCLIParser:
    """Test CLIParser event parsing."""

    def test_parse_text_content(self):
        """Test parsing text content from assistant message."""
        from cli.parser import CLIParser

        event = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello, world!"}]},
        }
        result = CLIParser.parse_event(event)
        assert result["type"] == "content"
        assert result["text"] == "Hello, world!"

    def test_parse_thinking_content(self):
        """Test parsing thinking content."""
        from cli.parser import CLIParser

        event = {
            "type": "assistant",
            "message": {
                "content": [{"type": "thinking", "thinking": "Let me think..."}]
            },
        }
        result = CLIParser.parse_event(event)
        assert result["type"] == "content"
        assert result["thinking"] == "Let me think..."

    def test_parse_tool_use(self):
        """Test parsing tool use content."""
        from cli.parser import CLIParser

        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "read_file",
                        "input": {"path": "/test"},
                    }
                ]
            },
        }
        result = CLIParser.parse_event(event)
        assert result["type"] == "tool_start"
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "read_file"

    def test_parse_text_delta(self):
        """Test parsing streaming text delta."""
        from cli.parser import CLIParser

        event = {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "streaming text"},
        }
        result = CLIParser.parse_event(event)
        assert result["type"] == "content"
        assert result["text"] == "streaming text"

    def test_parse_thinking_delta(self):
        """Test parsing streaming thinking delta."""
        from cli.parser import CLIParser

        event = {
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "thinking..."},
        }
        result = CLIParser.parse_event(event)
        assert result["type"] == "thinking"
        assert result["text"] == "thinking..."

    def test_parse_error(self):
        """Test parsing error event."""
        from cli.parser import CLIParser

        event = {"type": "error", "error": {"message": "Something went wrong"}}
        result = CLIParser.parse_event(event)
        assert result["type"] == "error"
        assert result["message"] == "Something went wrong"

    def test_parse_exit_success(self):
        """Test parsing exit event with success."""
        from cli.parser import CLIParser

        event = {"type": "exit", "code": 0}
        result = CLIParser.parse_event(event)
        assert result["type"] == "complete"
        assert result["status"] == "success"

    def test_parse_exit_failure(self):
        """Test parsing exit event with failure."""
        from cli.parser import CLIParser

        event = {"type": "exit", "code": 1}
        result = CLIParser.parse_event(event)
        assert result["type"] == "complete"
        assert result["status"] == "failed"

    def test_parse_invalid_event(self):
        """Test parsing returns None for unrecognized event."""
        from cli.parser import CLIParser

        result = CLIParser.parse_event({"type": "unknown"})
        assert result is None

    def test_parse_non_dict(self):
        """Test parsing returns None for non-dict input."""
        from cli.parser import CLIParser

        result = CLIParser.parse_event("not a dict")
        assert result is None


class TestCLISession:
    """Test CLISession."""

    def test_session_init(self):
        """Test CLISession initialization."""
        from cli.session import CLISession

        session = CLISession(
            workspace_path="/tmp/test",
            api_url="http://localhost:8082/v1",
            allowed_dirs=["/home/user/projects"],
        )
        assert session.workspace == "/tmp/test" or "test" in session.workspace
        assert session.api_url == "http://localhost:8082/v1"
        assert not session.is_busy

    def test_session_extract_session_id(self):
        """Test session ID extraction from various event formats."""
        from cli.session import CLISession

        session = CLISession("/tmp", "http://localhost:8082/v1")

        # Direct session_id field
        assert session._extract_session_id({"session_id": "abc123"}) == "abc123"
        assert session._extract_session_id({"sessionId": "abc123"}) == "abc123"

        # Nested in init
        assert (
            session._extract_session_id({"init": {"session_id": "nested123"}})
            == "nested123"
        )

        # Nested in result
        assert (
            session._extract_session_id({"result": {"session_id": "res123"}})
            == "res123"
        )

        # Conversation id
        assert (
            session._extract_session_id({"conversation": {"id": "conv123"}})
            == "conv123"
        )

        # No session ID
        assert session._extract_session_id({"type": "message"}) is None
        assert session._extract_session_id("not a dict") is None


class TestCLISessionManager:
    """Test CLISessionManager."""

    @pytest.mark.asyncio
    async def test_manager_create_session(self):
        """Test creating a new session."""
        from cli.manager import CLISessionManager

        manager = CLISessionManager(
            workspace_path="/tmp/test",
            api_url="http://localhost:8082/v1",
            max_sessions=5,
        )

        session, sid, is_new = await manager.get_or_create_session()
        assert session is not None
        assert sid.startswith("pending_")
        assert is_new is True

    @pytest.mark.asyncio
    async def test_manager_reuse_session(self):
        """Test reusing an existing session."""
        from cli.manager import CLISessionManager

        manager = CLISessionManager(
            workspace_path="/tmp/test",
            api_url="http://localhost:8082/v1",
        )

        # Create first session
        s1, sid1, is_new1 = await manager.get_or_create_session()

        # Request same session
        s2, sid2, is_new2 = await manager.get_or_create_session(session_id=sid1)

        assert s1 is s2
        assert is_new2 is False

    @pytest.mark.asyncio
    async def test_manager_stats(self):
        """Test manager stats."""
        from cli.manager import CLISessionManager

        manager = CLISessionManager(
            workspace_path="/tmp/test",
            api_url="http://localhost:8082/v1",
            max_sessions=10,
        )

        stats = manager.get_stats()
        assert stats["max_sessions"] == 10
        assert stats["active_sessions"] == 0
        assert stats["pending_sessions"] == 0
