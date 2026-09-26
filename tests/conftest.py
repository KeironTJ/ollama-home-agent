from pathlib import Path

import pytest

from home_agent.core.config import Settings
from home_agent.services.approvals import ApprovalStore
from home_agent.services.audit import AuditLog


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        config_file=tmp_path / "home-agent.config.json",
        proxmox_token_id="test@pve!agent",
        proxmox_token_secret="not-a-real-secret",
        proxmox_allowed_nodes=("pve",),
        proxmox_allowed_guests=(100,),
        ssh_hosts_json=(
            '{"minecraft":{"hostname":"192.0.2.10",'
            '"services":["minecraft"],"ports":[25565]}}'
        ),
        ssh_key_file=tmp_path / "key",
        approval_ttl_seconds=60,
    )


@pytest.fixture
def audit(settings: Settings) -> AuditLog:
    return AuditLog(settings.database_path)


@pytest.fixture
def approvals(settings: Settings, audit: AuditLog) -> ApprovalStore:
    return ApprovalStore(audit, settings.approval_ttl_seconds)
