from __future__ import annotations

from typing import Any


def build_artifact(tool_name: str, result: Any) -> dict[str, Any] | None:
    if isinstance(result, dict) and ("error" in result or "pending_approval" in result):
        return None
    artifact_types = {
        "proxmox_inventory": "infrastructure",
        "proxmox_node_status": "node_status",
        "proxmox_guest_status": "guest_status",
        "proxmox_recent_tasks": "task_list",
        "discover_guest": "guest_list",
        "tcp_port_check": "port_status",
        "ssh_service_status": "service_status",
        "ssh_system_resources": "system_resources",
    }
    artifact_type = artifact_types.get(tool_name)
    if artifact_type is None:
        return None
    return {"type": artifact_type, "source": tool_name, "data": result}
