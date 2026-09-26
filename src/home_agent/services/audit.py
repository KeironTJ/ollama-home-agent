from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..core.security import bounded_redacted


class AuditLog:
    def __init__(self, path: Path, max_output_chars: int = 8_000):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.max_output_chars = max_output_chars
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    session_id TEXT,
                    name TEXT,
                    input TEXT,
                    output TEXT,
                    success INTEGER
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    action TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    description TEXT NOT NULL,
                    decided_at TEXT,
                    outcome TEXT
                );
                """
            )

    def record(
        self,
        event_type: str,
        *,
        session_id: str | None = None,
        name: str | None = None,
        input_data: Any = None,
        output_data: Any = None,
        success: bool | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        input_text = bounded_redacted(input_data, self.max_output_chars) if input_data is not None else None
        output_text = bounded_redacted(output_data, self.max_output_chars) if output_data is not None else None
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO audit_events
                   (created_at, event_type, session_id, name, input, output, success)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (now, event_type, session_id, name, input_text, output_text, success),
            )

    @staticmethod
    def encode(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
