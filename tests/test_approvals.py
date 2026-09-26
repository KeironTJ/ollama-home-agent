from datetime import UTC, datetime, timedelta

import pytest

from home_agent.approvals import ApprovalError, ApprovalStore
from home_agent.audit import AuditLog


def test_approval_is_explicit_and_single_use(approvals: ApprovalStore) -> None:
    pending = approvals.create("start_guest", {"guest_id": 100}, "Start guest 100")
    calls = []

    result = approvals.decide(
        pending.id,
        True,
        lambda action, arguments: calls.append((action, arguments)) or {"ok": True},
    )

    assert result["status"] == "completed"
    assert calls == [("start_guest", {"guest_id": 100})]
    with pytest.raises(ApprovalError, match="already been completed"):
        approvals.decide(pending.id, True, lambda *_: None)
    assert len(calls) == 1


def test_rejection_never_executes(approvals: ApprovalStore) -> None:
    pending = approvals.create("restart_service", {"service": "minecraft"}, "Restart")
    called = False

    def executor(*_args):
        nonlocal called
        called = True

    result = approvals.decide(pending.id, False, executor)
    assert result["status"] == "rejected"
    assert called is False


def test_expired_approval_never_executes(approvals: ApprovalStore, audit: AuditLog) -> None:
    pending = approvals.create("start_guest", {"guest_id": 100}, "Start")
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with audit._connect() as connection:
        connection.execute("UPDATE approvals SET expires_at = ? WHERE id = ?", (expired, pending.id))

    with pytest.raises(ApprovalError, match="expired"):
        approvals.decide(pending.id, True, lambda *_: pytest.fail("must not execute"))
    assert approvals.get(pending.id).status == "expired"

