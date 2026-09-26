from __future__ import annotations

"""Transactional approval lifecycle service."""

import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from .audit import AuditLog


@dataclass(frozen=True)
class PendingApproval:
    id: str
    action: str
    arguments: dict[str, Any]
    description: str
    expires_at: str
    status: str = "pending"


class ApprovalError(RuntimeError):
    pass


class ApprovalStore:
    def __init__(self, audit: AuditLog, ttl_seconds: int):
        self.audit = audit
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()

    def create(self, action: str, arguments: dict[str, Any], description: str) -> PendingApproval:
        now = datetime.now(UTC)
        approval = PendingApproval(
            id=str(uuid.uuid4()),
            action=action,
            arguments=arguments,
            description=description,
            expires_at=(now + timedelta(seconds=self.ttl_seconds)).isoformat(),
        )
        with self.audit._connect() as connection:
            connection.execute(
                """INSERT INTO approvals
                   (id, created_at, expires_at, status, action, arguments, description)
                   VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
                (
                    approval.id,
                    now.isoformat(),
                    approval.expires_at,
                    action,
                    self.audit.encode(arguments),
                    description,
                ),
            )
        self.audit.record("approval_requested", name=action, input_data=arguments, output_data=asdict(approval))
        return approval

    def decide(
        self,
        approval_id: str,
        approved: bool,
        executor: Callable[[str, dict[str, Any]], Any],
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        expired = False
        with self._lock, self.audit._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
            if row is None:
                raise ApprovalError("Approval ID was not found")
            if row["status"] != "pending":
                raise ApprovalError(f"Approval has already been {row['status']}")
            if datetime.fromisoformat(row["expires_at"]) <= now:
                connection.execute(
                    "UPDATE approvals SET status = 'expired', decided_at = ? WHERE id = ?",
                    (now.isoformat(), approval_id),
                )
                expired = True
            else:
                next_status = "executing" if approved else "rejected"
                connection.execute(
                    "UPDATE approvals SET status = ?, decided_at = ? WHERE id = ? AND status = 'pending'",
                    (next_status, now.isoformat(), approval_id),
                )
            action = row["action"]
            arguments = json.loads(row["arguments"])
        if expired:
            self.audit.record("approval_expired", name=action, input_data=arguments, success=False)
            raise ApprovalError("Approval has expired")

        if not approved:
            result = {"approval_id": approval_id, "status": "rejected"}
            self.audit.record("approval_rejected", name=action, input_data=arguments, output_data=result, success=True)
            return result

        try:
            outcome = executor(action, arguments)
        except Exception as exc:
            safe_error = str(exc)
            with self.audit._connect() as connection:
                connection.execute(
                    "UPDATE approvals SET status = 'failed', outcome = ? WHERE id = ?",
                    (safe_error, approval_id),
                )
            self.audit.record("approval_executed", name=action, input_data=arguments, output_data=safe_error, success=False)
            raise

        with self.audit._connect() as connection:
            connection.execute(
                "UPDATE approvals SET status = 'completed', outcome = ? WHERE id = ?",
                (self.audit.encode(outcome), approval_id),
            )
        result = {"approval_id": approval_id, "status": "completed", "outcome": outcome}
        self.audit.record("approval_executed", name=action, input_data=arguments, output_data=outcome, success=True)
        return result

    def get(self, approval_id: str) -> PendingApproval | None:
        with self.audit._connect() as connection:
            row = connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            return None
        return PendingApproval(
            id=row["id"],
            action=row["action"],
            arguments=json.loads(row["arguments"]),
            description=row["description"],
            expires_at=row["expires_at"],
            status=row["status"],
        )
