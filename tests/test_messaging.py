"""Tests for messaging/ module."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock


class TestMessagingModels:
    """Test messaging models."""

    def test_incoming_message_creation(self):
        """Test IncomingMessage dataclass."""
        from messaging.models import IncomingMessage

        msg = IncomingMessage(
            text="Hello",
            chat_id="123",
            user_id="456",
            message_id="789",
            platform="telegram",
        )
        assert msg.text == "Hello"
        assert msg.chat_id == "123"
        assert msg.platform == "telegram"
        assert msg.is_reply() is False

    def test_incoming_message_with_reply(self):
        """Test IncomingMessage as a reply."""
        from messaging.models import IncomingMessage

        msg = IncomingMessage(
            text="Reply text",
            chat_id="123",
            user_id="456",
            message_id="789",
            platform="discord",
            reply_to_message_id="100",
        )
        assert msg.is_reply() is True
        assert msg.reply_to_message_id == "100"

    def test_outgoing_message_creation(self):
        """Test OutgoingMessage dataclass."""
        from messaging.models import OutgoingMessage

        msg = OutgoingMessage(
            text="Response",
            chat_id="123",
            parse_mode="markdown",
        )
        assert msg.text == "Response"
        assert msg.parse_mode == "markdown"
        assert msg.edit_message_id is None

    def test_message_context(self):
        """Test MessageContext dataclass."""
        from messaging.models import MessageContext

        ctx = MessageContext(session_id="sess123", is_new_session=False)
        assert ctx.session_id == "sess123"
        assert ctx.is_new_session is False


class TestMessagingBase:
    """Test MessagingPlatform ABC."""

    def test_platform_is_abstract(self):
        """Verify MessagingPlatform cannot be instantiated."""
        from messaging.base import MessagingPlatform

        with pytest.raises(TypeError):
            MessagingPlatform()


class TestSessionStore:
    """Test SessionStore."""

    def test_session_store_init(self, tmp_path):
        """Test SessionStore initialization."""
        from messaging.session import SessionStore

        store = SessionStore(storage_path=str(tmp_path / "sessions.json"))
        assert store._sessions == {}

    def test_save_and_get_session(self, tmp_path):
        """Test saving and retrieving a session."""
        from messaging.session import SessionStore

        store = SessionStore(storage_path=str(tmp_path / "sessions.json"))

        store.save_session(
            session_id="sess_123",
            chat_id="chat_456",
            initial_msg_id="msg_789",
            platform="telegram",
        )

        # Retrieve by message
        found = store.get_session_by_msg("chat_456", "msg_789", "telegram")
        assert found == "sess_123"

    def test_update_last_message(self, tmp_path):
        """Test updating last message in session."""
        from messaging.session import SessionStore

        store = SessionStore(storage_path=str(tmp_path / "sessions.json"))

        store.save_session("sess_1", "chat_1", "msg_1", "telegram")
        store.update_last_message("sess_1", "msg_2")

        # Should find session by new message too
        found = store.get_session_by_msg("chat_1", "msg_2", "telegram")
        assert found == "sess_1"

    def test_get_session_record(self, tmp_path):
        """Test getting full session record."""
        from messaging.session import SessionStore

        store = SessionStore(storage_path=str(tmp_path / "sessions.json"))
        store.save_session("sess_1", "chat_1", "msg_1", "telegram")

        record = store.get_session_record("sess_1")
        assert record is not None
        assert record.session_id == "sess_1"
        assert record.platform == "telegram"

    def test_session_not_found(self, tmp_path):
        """Test getting non-existent session returns None."""
        from messaging.session import SessionStore

        store = SessionStore(storage_path=str(tmp_path / "sessions.json"))

        found = store.get_session_by_msg("notexist", "notexist", "telegram")
        assert found is None


class TestTreeQueueManager:
    """Test TreeQueueManager."""

    def test_tree_queue_manager_init(self):
        """Test TreeQueueManager initialization."""
        from messaging.tree_queue import TreeQueueManager

        mgr = TreeQueueManager()
        assert mgr._trees == {}

    def test_tree_not_busy_initially(self):
        """Test tree is not busy when no messages."""
        from messaging.tree_queue import TreeQueueManager

        mgr = TreeQueueManager()
        assert mgr.is_tree_busy("nonexistent") is False

    def test_get_queue_size_empty(self):
        """Test queue size is 0 for non-existent node."""
        from messaging.tree_queue import TreeQueueManager

        mgr = TreeQueueManager()
        assert mgr.get_queue_size("nonexistent") == 0

    @pytest.mark.asyncio
    async def test_create_tree_and_enqueue(self):
        """Test creating a tree and enqueueing."""
        from messaging.tree_queue import TreeQueueManager
        from messaging.models import IncomingMessage

        mgr = TreeQueueManager()
        processed = []

        async def processor(node_id, node):
            processed.append(node_id)

        incoming = IncomingMessage(
            text="test", chat_id="1", user_id="1", message_id="1", platform="test"
        )

        tree = await mgr.create_tree("1", incoming, "status_1")
        was_queued = await mgr.enqueue("1", processor)

        # First message should process immediately, not queue
        assert was_queued is False

    def test_cancel_tree_empty(self):
        """Test cancelling non-existent tree."""
        from messaging.tree_queue import TreeQueueManager

        mgr = TreeQueueManager()
        cancelled = mgr.cancel_tree("nonexistent")
        assert cancelled == []
