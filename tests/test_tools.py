from unittest.mock import Mock

import pytest

from home_agent.tools import DiagnosticTools, ToolError


def make_tools(settings, approvals, audit, proxmox=None):
    return DiagnosticTools(settings, proxmox or Mock(), approvals, audit)


def test_proxmox_allowlists_block_unknown_targets(settings, approvals, audit) -> None:
    tools = make_tools(settings, approvals, audit)
    with pytest.raises(ToolError, match="not allowlisted"):
        tools.proxmox_node_status("other")
    with pytest.raises(ToolError, match="not allowlisted"):
        tools.proxmox_guest_status("pve", 999, "qemu")


def test_inventory_filters_non_allowlisted_guests(settings, approvals, audit) -> None:
    proxmox = Mock()
    proxmox.request.side_effect = [
        [{"node": "pve", "status": "online"}, {"node": "other", "status": "online"}],
        [
            {"vmid": 100, "node": "pve", "name": "minecraft", "type": "qemu"},
            {"vmid": 999, "node": "pve", "name": "secret", "type": "qemu"},
        ],
    ]
    result = make_tools(settings, approvals, audit, proxmox).proxmox_inventory()
    assert [node["node"] for node in result["nodes"]] == ["pve"]
    assert [guest["vmid"] for guest in result["guests"]] == [100]


def test_ssh_service_and_port_allowlists(settings, approvals, audit) -> None:
    tools = make_tools(settings, approvals, audit)
    with pytest.raises(ToolError, match="Service"):
        tools.ssh_service_status("minecraft", "sshd")
    with pytest.raises(ToolError, match="port"):
        tools.tcp_port_check("minecraft", 22)
    with pytest.raises(ToolError, match="host"):
        tools.ssh_system_resources("unknown")


def test_mutating_tool_only_creates_pending_approval(settings, approvals, audit) -> None:
    proxmox = Mock()
    tools = make_tools(settings, approvals, audit, proxmox)
    result = tools.request_start_guest("pve", 100, "qemu")
    pending = result["pending_approval"]
    assert pending["status"] == "pending"
    proxmox.request.assert_not_called()

