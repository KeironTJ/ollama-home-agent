from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..core.security import bounded_redacted


class ChatHistory:
    def __init__(
        self,
        path: Path,
        max_message_chars: int = 10_000,
        max_messages_per_conversation: int = 200,
        max_conversations: int = 100,
    ):
        self.path = path
        self.max_message_chars = max_message_chars
        self.max_messages_per_conversation = max_messages_per_conversation
        self.max_conversations = max_conversations
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation
                    ON chat_messages(conversation_id, id);
                """
            )

    def add_message(self, conversation_id: str, role: str, content: str) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("Chat history role must be user or assistant")
        now = datetime.now(UTC).isoformat()
        safe_content = bounded_redacted(content, self.max_message_chars)
        title = bounded_redacted(content.replace("\n", " ").strip(), 80) or "New conversation"
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO conversations (id, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at""",
                (conversation_id, title, now, now),
            )
            connection.execute(
                """INSERT INTO chat_messages (conversation_id, role, content, created_at)
                   VALUES (?, ?, ?, ?)""",
                (conversation_id, role, safe_content, now),
            )
            connection.execute(
                """DELETE FROM chat_messages
                   WHERE conversation_id = ? AND id NOT IN (
                       SELECT id FROM chat_messages
                       WHERE conversation_id = ?
                       ORDER BY id DESC LIMIT ?
                   )""",
                (
                    conversation_id,
                    conversation_id,
                    self.max_messages_per_conversation,
                ),
            )
            stale = connection.execute(
                "SELECT id FROM conversations ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
                (self.max_conversations,),
            ).fetchall()
            if stale:
                connection.executemany(
                    "DELETE FROM conversations WHERE id = ?",
                    ((row["id"],) for row in stale),
                )

    def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT c.id, c.title, c.created_at, c.updated_at,
                          COUNT(m.id) AS message_count
                   FROM conversations c
                   LEFT JOIN chat_messages m ON m.conversation_id = c.id
                   GROUP BY c.id
                   ORDER BY c.updated_at DESC
                   LIMIT ?""",
                (min(max(limit, 1), 100),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id, role, content, created_at
                   FROM chat_messages
                   WHERE conversation_id = ?
                   ORDER BY id""",
                (conversation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )
        return cursor.rowcount > 0
