from home_agent.core.security import bounded_redacted, redact_secrets
from home_agent.services.audit import AuditLog


def test_redacts_proxmox_and_common_secrets() -> None:
    value = (
        "Authorization: PVEAPIToken=user@pve!agent=supersecret "
        "password=hunter2 Bearer abc.def.ghi"
    )
    result = redact_secrets(value)
    assert "supersecret" not in result
    assert "hunter2" not in result
    assert "abc.def.ghi" not in result
    assert result.count("[REDACTED]") >= 3


def test_bounds_stored_output() -> None:
    result = bounded_redacted("x" * 100, 20)
    assert result.startswith("x" * 20)
    assert "truncated 80 characters" in result


def test_audit_log_redacts_before_storage(tmp_path) -> None:
    audit = AuditLog(tmp_path / "audit.sqlite3")
    audit.record(
        "tool_call",
        input_data={"authorization": "Bearer audit-secret"},
        output_data="password=also-secret",
    )
    with audit._connect() as connection:
        row = connection.execute("SELECT input, output FROM audit_events").fetchone()
    assert "audit-secret" not in row["input"]
    assert "also-secret" not in row["output"]
    assert "[REDACTED]" in row["input"]
    assert "[REDACTED]" in row["output"]
