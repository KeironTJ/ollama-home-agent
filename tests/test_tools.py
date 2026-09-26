from unittest.mock import Mock

import pytest

from home_agent.tools import DiagnosticTools, ToolError


def make_tools(settings, approvals, audit, proxmox=None):
    return DiagnosticTools(settings, proxmox or Mock(), approvals, audit)


def test_proxmox_allowlists_block_unknown_targets(settings, approvals, audit) -> None:
    tools = make_tools(settings, approvals, audit)
    with pytest.raises(ToolError, match="not allowlisted"):
        tools.invoke("proxmox_node_status", {"node": "other"})
    with pytest.raises(ToolError, match="not allowlisted"):
        tools.invoke(
            "proxmox_guest_status",
            {"node": "pve", "guest_id": 999, "guest_type": "qemu"},
        )


def test_inventory_filters_non_allowlisted_guests(settings, approvals, audit) -> None:
    proxmox = Mock()
    proxmox.request.side_effect = [
        [{"node": "pve", "status": "online"}, {"node": "other", "status": "online"}],
        [
            {"vmid": 100, "node": "pve", "name": "minecraft", "type": "qemu"},
            {"vmid": 999, "node": "pve", "name": "secret", "type": "qemu"},
        ],
    ]
    result = make_tools(settings, approvals, audit, proxmox).invoke(
        "proxmox_inventory",
        {},
    )
    assert [node["node"] for node in result["nodes"]] == ["pve"]
    assert [guest["vmid"] for guest in result["guests"]] == [100]


def test_ssh_service_and_port_allowlists(settings, approvals, audit) -> None:
    tools = make_tools(settings, approvals, audit)
    with pytest.raises(ToolError, match="Service"):
        tools.invoke(
            "ssh_service_status",
            {"host": "minecraft", "service": "sshd"},
        )
    with pytest.raises(ToolError, match="port"):
        tools.invoke("tcp_port_check", {"host": "minecraft", "port": 22})
    with pytest.raises(ToolError, match="host"):
        tools.invoke("ssh_system_resources", {"host": "unknown"})


def test_mutating_tool_only_creates_pending_approval(settings, approvals, audit) -> None:
    proxmox = Mock()
    tools = make_tools(settings, approvals, audit, proxmox)
    result = tools.invoke(
        "request_start_guest",
        {"node": "pve", "guest_id": 100, "guest_type": "qemu"},
    )
    pending = result["pending_approval"]
    assert pending["status"] == "pending"
    proxmox.request.assert_not_called()


def test_unconfigured_ssh_tools_are_hidden_from_model(settings, approvals, audit) -> None:
    settings.ssh_hosts_json = "{}"
    proxmox = Mock()
    proxmox.configured = True
    tools = make_tools(settings, approvals, audit, proxmox)
    names = {schema["function"]["name"] for schema in tools.schemas}
    assert "proxmox_inventory" in names
    assert "ssh_service_status" not in names
    assert "request_restart_service" not in names
