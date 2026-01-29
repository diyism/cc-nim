"""
Session Store for Messaging Platforms

Provides persistent storage for mapping platform messages to Claude CLI session IDs.
This enables conversation continuation when replying to old messages.
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional, Dict
from dataclasses import dataclass, asdict
import threading

logger = logging.getLogger(__name__)


@dataclass
class SessionRecord:
    """A single session record."""

    session_id: str
    chat_id: str  # Changed to str for platform-agnostic support
    initial_msg_id: str
    last_msg_id: str
    platform: str  # "telegram", "discord", etc.
    created_at: str
    updated_at: str


class SessionStore:
    """
    Persistent storage for message ↔ Claude session mappings.

    Uses a JSON file for storage with thread-safe operations.
    Platform-agnostic: works with any messaging platform.
    """

    def __init__(self, storage_path: str = "sessions.json"):
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._sessions: Dict[str, SessionRecord] = {}  # session_id -> record
        self._msg_to_session: Dict[
            str, str
        ] = {}  # "platform:chat_id:msg_id" -> session_id
        self._load()

    def _make_key(self, platform: str, chat_id: str, msg_id: str) -> str:
        """Create a unique key from platform, chat_id and msg_id."""
        return f"{platform}:{chat_id}:{msg_id}"

    def _load(self) -> None:
        """Load sessions from disk."""
        if not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for sid, record_data in data.get("sessions", {}).items():
                # Handle legacy records without platform field
                if "platform" not in record_data:
                    record_data["platform"] = "telegram"
                # Convert int to str for backwards compatibility
                for field in ["chat_id", "initial_msg_id", "last_msg_id"]:
                    if isinstance(record_data.get(field), int):
                        record_data[field] = str(record_data[field])

                record = SessionRecord(**record_data)
                self._sessions[sid] = record
                # Index by initial and last message
                self._msg_to_session[
                    self._make_key(
                        record.platform, record.chat_id, record.initial_msg_id
                    )
                ] = sid
                self._msg_to_session[
                    self._make_key(record.platform, record.chat_id, record.last_msg_id)
                ] = sid

            logger.info(
                f"Loaded {len(self._sessions)} sessions from {self.storage_path}"
            )
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")

    def _save(self) -> None:
        """Persist sessions to disk."""
        try:
            data = {
                "sessions": {
                    sid: asdict(record) for sid, record in self._sessions.items()
                }
            }
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")

    def save_session(
        self,
        session_id: str,
        chat_id: str,
        initial_msg_id: str,
        platform: str = "telegram",
    ) -> None:
        """
        Save a new session mapping.

        Args:
            session_id: Claude CLI session ID
            chat_id: Chat ID (platform-specific)
            initial_msg_id: The message ID that started this session
            platform: Messaging platform name
        """
        with self._lock:
            now = datetime.utcnow().isoformat()
            record = SessionRecord(
                session_id=session_id,
                chat_id=str(chat_id),
                initial_msg_id=str(initial_msg_id),
                last_msg_id=str(initial_msg_id),
                platform=platform,
                created_at=now,
                updated_at=now,
            )
            self._sessions[session_id] = record
            self._msg_to_session[
                self._make_key(platform, str(chat_id), str(initial_msg_id))
            ] = session_id
            self._save()
            logger.info(
                f"Saved session {session_id} for {platform} chat {chat_id}, msg {initial_msg_id}"
            )

    def get_session_by_msg(
        self, chat_id: str, msg_id: str, platform: str = "telegram"
    ) -> Optional[str]:
        """
        Look up a session ID by a message that's part of that session.

        Args:
            chat_id: Chat ID
            msg_id: Message ID to look up
            platform: Messaging platform name

        Returns:
            Session ID if found, None otherwise
        """
        with self._lock:
            key = self._make_key(platform, str(chat_id), str(msg_id))
            return self._msg_to_session.get(key)

    def update_last_message(self, session_id: str, msg_id: str) -> None:
        """
        Update the last message ID for a session.

        Args:
            session_id: Claude session ID
            msg_id: New last message ID
        """
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"Session {session_id} not found for update")
                return

            record = self._sessions[session_id]

            # Update record
            record.last_msg_id = str(msg_id)
            record.updated_at = datetime.utcnow().isoformat()

            # Update index - add new key, keep old one for chain lookups
            new_key = self._make_key(record.platform, record.chat_id, str(msg_id))
            self._msg_to_session[new_key] = session_id

            self._save()
            logger.debug(f"Updated session {session_id} last_msg to {msg_id}")

    def get_session_record(self, session_id: str) -> Optional[SessionRecord]:
        """Get full session record."""
        with self._lock:
            return self._sessions.get(session_id)

    def cleanup_old_sessions(self, max_age_days: int = 30) -> int:
        """
        Remove sessions older than max_age_days.

        Returns:
            Number of sessions removed
        """
        with self._lock:
            cutoff = datetime.utcnow()
            removed = 0

            to_remove = []
            for sid, record in self._sessions.items():
                try:
                    created = datetime.fromisoformat(record.created_at)
                    age_days = (cutoff - created).days
                    if age_days > max_age_days:
                        to_remove.append(sid)
                except Exception:
                    pass

            for sid in to_remove:
                record = self._sessions.pop(sid)
                # Remove index entries
                self._msg_to_session.pop(
                    self._make_key(
                        record.platform, record.chat_id, record.initial_msg_id
                    ),
                    None,
                )
                self._msg_to_session.pop(
                    self._make_key(record.platform, record.chat_id, record.last_msg_id),
                    None,
                )
                removed += 1

            if removed:
                self._save()
                logger.info(f"Cleaned up {removed} old sessions")

            return removed
