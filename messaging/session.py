"""
Session Store for Messaging Platforms

Provides persistent storage for mapping platform messages to Claude CLI session IDs
and message trees for conversation continuation.
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
    chat_id: str
    initial_msg_id: str
    last_msg_id: str
    platform: str
    created_at: str
    updated_at: str


class SessionStore:
    """
    Persistent storage for message ↔ Claude session mappings and message trees.

    Uses a JSON file for storage with thread-safe operations.
    Platform-agnostic: works with any messaging platform.
    """

    def __init__(self, storage_path: str = "sessions.json"):
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._sessions: Dict[str, SessionRecord] = {}
        self._msg_to_session: Dict[
            str, str
        ] = {}  # "platform:chat_id:msg_id" -> session_id
        self._trees: Dict[str, dict] = {}  # root_id -> tree data
        self._node_to_tree: Dict[str, str] = {}  # node_id -> root_id
        self._load()

    def _make_key(self, platform: str, chat_id: str, msg_id: str) -> str:
        """Create a unique key from platform, chat_id and msg_id."""
        return f"{platform}:{chat_id}:{msg_id}"

    def _load(self) -> None:
        """Load sessions and trees from disk."""
        if not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Load sessions (legacy support)
            for sid, record_data in data.get("sessions", {}).items():
                if "platform" not in record_data:
                    record_data["platform"] = "telegram"
                for field in ["chat_id", "initial_msg_id", "last_msg_id"]:
                    if isinstance(record_data.get(field), int):
                        record_data[field] = str(record_data[field])

                record = SessionRecord(**record_data)
                self._sessions[sid] = record
                self._msg_to_session[
                    self._make_key(
                        record.platform, record.chat_id, record.initial_msg_id
                    )
                ] = sid
                self._msg_to_session[
                    self._make_key(record.platform, record.chat_id, record.last_msg_id)
                ] = sid

            # Load trees
            self._trees = data.get("trees", {})
            self._node_to_tree = data.get("node_to_tree", {})

            logger.info(
                f"Loaded {len(self._sessions)} sessions and {len(self._trees)} trees from {self.storage_path}"
            )
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")

    def _save(self) -> None:
        """Persist sessions and trees to disk."""
        try:
            data = {
                "sessions": {
                    sid: asdict(record) for sid, record in self._sessions.items()
                },
                "trees": self._trees,
                "node_to_tree": self._node_to_tree,
            }
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")

    # ==================== Session Methods ====================

    def save_session(
        self,
        session_id: str,
        chat_id: str,
        initial_msg_id: str,
        platform: str = "telegram",
    ) -> None:
        """Save a new session mapping."""
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
        """Look up a session ID by a message that's part of that session."""
        with self._lock:
            key = self._make_key(platform, str(chat_id), str(msg_id))
            return self._msg_to_session.get(key)

    def update_last_message(self, session_id: str, msg_id: str) -> None:
        """Update the last message ID for a session."""
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"Session {session_id} not found for update")
                return

            record = self._sessions[session_id]
            record.last_msg_id = str(msg_id)
            record.updated_at = datetime.utcnow().isoformat()
            new_key = self._make_key(record.platform, record.chat_id, str(msg_id))
            self._msg_to_session[new_key] = session_id
            self._save()
            logger.debug(f"Updated session {session_id} last_msg to {msg_id}")

    def rename_session(self, old_id: str, new_id: str) -> bool:
        """Rename a session ID, migrating all message mappings."""
        with self._lock:
            if old_id not in self._sessions:
                logger.warning(f"Session {old_id} not found for rename to {new_id}")
                return False

            record = self._sessions.pop(old_id)
            record.session_id = new_id
            record.updated_at = datetime.utcnow().isoformat()
            self._sessions[new_id] = record

            items_to_update = [
                k for k, v in self._msg_to_session.items() if v == old_id
            ]
            for key in items_to_update:
                self._msg_to_session[key] = new_id

            self._save()
            logger.info(
                f"Renamed session {old_id} to {new_id} ({len(items_to_update)} mappings updated)"
            )
            return True

    def get_session_record(self, session_id: str) -> Optional[SessionRecord]:
        """Get full session record."""
        with self._lock:
            return self._sessions.get(session_id)

    def cleanup_old_sessions(self, max_age_days: int = 30) -> int:
        """Remove sessions older than max_age_days."""
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

    # ==================== Tree Methods ====================

    def save_tree(self, root_id: str, tree_data: dict) -> None:
        """
        Save a message tree.

        Args:
            root_id: Root node ID of the tree
            tree_data: Serialized tree data from tree.to_dict()
        """
        with self._lock:
            self._trees[root_id] = tree_data

            # Update node-to-tree mapping
            for node_id in tree_data.get("nodes", {}).keys():
                self._node_to_tree[node_id] = root_id

            self._save()
            logger.debug(f"Saved tree {root_id}")

    def get_tree(self, root_id: str) -> Optional[dict]:
        """Get a tree by its root ID."""
        with self._lock:
            return self._trees.get(root_id)

    def get_tree_by_node(self, node_id: str) -> Optional[dict]:
        """Get the tree containing a node."""
        with self._lock:
            root_id = self._node_to_tree.get(node_id)
            if not root_id:
                return None
            return self._trees.get(root_id)

    def get_tree_root_for_node(self, node_id: str) -> Optional[str]:
        """Get the root ID of the tree containing a node."""
        with self._lock:
            return self._node_to_tree.get(node_id)

    def register_node(self, node_id: str, root_id: str) -> None:
        """Register a node ID to a tree root."""
        with self._lock:
            self._node_to_tree[node_id] = root_id
            self._save()

    def update_tree_node(self, root_id: str, node_id: str, node_data: dict) -> None:
        """Update a specific node in a tree."""
        with self._lock:
            if root_id not in self._trees:
                logger.warning(f"Tree {root_id} not found")
                return

            if "nodes" not in self._trees[root_id]:
                self._trees[root_id]["nodes"] = {}

            self._trees[root_id]["nodes"][node_id] = node_data
            self._node_to_tree[node_id] = root_id
            self._save()

    def cleanup_old_trees(self, max_age_days: int = 30) -> int:
        """Remove trees older than max_age_days."""
        with self._lock:
            cutoff = datetime.utcnow()
            removed = 0
            to_remove = []

            for root_id, tree_data in self._trees.items():
                try:
                    nodes = tree_data.get("nodes", {})
                    root_node = nodes.get(root_id, {})
                    created_str = root_node.get("created_at")
                    if created_str:
                        created = datetime.fromisoformat(created_str)
                        age_days = (cutoff - created).days
                        if age_days > max_age_days:
                            to_remove.append(root_id)
                except Exception:
                    pass

            for root_id in to_remove:
                tree_data = self._trees.pop(root_id)
                # Remove node mappings
                for node_id in tree_data.get("nodes", {}).keys():
                    self._node_to_tree.pop(node_id, None)
                removed += 1

            if removed:
                self._save()
                logger.info(f"Cleaned up {removed} old trees")

            return removed
