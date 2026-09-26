from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from ..core.config import Settings
from ..integrations import ProxmoxClient
from ..services.approvals import ApprovalStore
from .base import ToolError, tool_schema


class ProxmoxToolSet:
    approved_actions = frozenset({"start_guest", "reboot_guest"})

    def __init__(
        self,
        settings: Settings,
        client: ProxmoxClient,
        approvals: ApprovalStore,
    ):
        self.settings = settings
        self.client = client
        self.approvals = approvals

    @property
    def handlers(self) -> dict[str, Callable[..., Any]]:
        return {
            "proxmox_inventory": self.inventory,
            "proxmox_node_status": self.node_status,
            "proxmox_guest_status": self.guest_status,
            "proxmox_recent_tasks": self.recent_tasks,
            "discover_guest": self.discover_guest,
            "request_start_guest": self.request_start_guest,
            "request_reboot_guest": self.request_reboot_guest,
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        if not self.client.configured or not self.settings.proxmox_allowed_nodes:
            return []
        string = {"type": "string"}
        node = {
            "type": "string",
            "enum": sorted(self.settings.proxmox_allowed_nodes),
        }
        schemas = [
            tool_schema(
                "proxmox_inventory",
                "List allowlisted Proxmox nodes and guests.",
                {},
                [],
            ),
            tool_schema(
                "proxmox_node_status",
                "Get status for one allowlisted node.",
                {"node": node},
                ["node"],
            ),
            tool_schema(
                "proxmox_recent_tasks",
                "List recent tasks on an allowlisted node.",
                {"node": node},
                ["node"],
            ),
        ]
        if not self.settings.proxmox_allowed_guests:
            return schemas
        guest = {
            "type": "integer",
            "enum": sorted(self.settings.proxmox_allowed_guests),
        }
        guest_type = {"type": "string", "enum": ["qemu", "lxc"]}
        schemas.extend(
            [
                tool_schema(
                    "proxmox_guest_status",
                    "Get current status for one allowlisted VM or LXC.",
                    {"node": node, "guest_id": guest, "guest_type": guest_type},
                    ["node", "guest_id", "guest_type"],
                ),
                tool_schema(
                    "discover_guest",
                    "Find allowlisted guests by name or numeric ID.",
                    {"query": string},
                    ["query"],
                ),
                tool_schema(
                    "request_start_guest",
                    "Request explicit approval to start an allowlisted Proxmox guest.",
                    {"node": node, "guest_id": guest, "guest_type": guest_type},
                    ["node", "guest_id", "guest_type"],
                ),
                tool_schema(
                    "request_reboot_guest",
                    "Request explicit approval to reboot an allowlisted Proxmox guest.",
                    {"node": node, "guest_id": guest, "guest_type": guest_type},
                    ["node", "guest_id", "guest_type"],
                ),
            ]
        )
        return schemas

    def _allow_node(self, node: str) -> None:
        if node not in self.settings.proxmox_allowed_nodes:
            raise ToolError(f"Proxmox node '{node}' is not allowlisted")

    def _allow_guest(self, guest_id: int) -> None:
        if guest_id not in self.settings.proxmox_allowed_guests:
            raise ToolError(f"Proxmox guest '{guest_id}' is not allowlisted")

    def _allow_guest_target(
        self,
        node: str,
        guest_id: int,
        guest_type: str,
    ) -> None:
        self._allow_node(node)
        self._allow_guest(guest_id)
        if guest_type not in ("qemu", "lxc"):
            raise ToolError("guest_type must be qemu or lxc")

    def _inventory(self) -> list[dict[str, Any]]:
        resources = self.client.request(
            "GET",
            "cluster/resources",
            params={"type": "vm"},
        ) or []
        return [
            {
                key: item.get(key)
                for key in (
                    "vmid",
                    "name",
                    "type",
                    "node",
                    "status",
                    "uptime",
                    "cpu",
                    "mem",
                    "maxmem",
                )
            }
            for item in resources
            if item.get("vmid") in self.settings.proxmox_allowed_guests
            and item.get("node") in self.settings.proxmox_allowed_nodes
        ]

    def inventory(self) -> dict[str, Any]:
        nodes = self.client.request("GET", "nodes") or []
        safe_nodes = [
            {
                key: item.get(key)
                for key in ("node", "status", "uptime", "cpu", "mem", "maxmem")
            }
            for item in nodes
            if item.get("node") in self.settings.proxmox_allowed_nodes
        ]
        return {"nodes": safe_nodes, "guests": self._inventory()}

    def node_status(self, node: str) -> Any:
        self._allow_node(node)
        data = self.client.request("GET", f"nodes/{node}/status") or {}
        allowed = (
            "uptime",
            "loadavg",
            "cpu",
            "memory",
            "swap",
            "rootfs",
            "pveversion",
            "kversion",
        )
        return {key: data.get(key) for key in allowed}

    def guest_status(self, node: str, guest_id: int, guest_type: str) -> Any:
        self._allow_guest_target(node, guest_id, guest_type)
        data = self.client.request(
            "GET",
            f"nodes/{node}/{guest_type}/{guest_id}/status/current",
        ) or {}
        allowed = (
            "vmid",
            "name",
            "status",
            "uptime",
            "cpu",
            "cpus",
            "mem",
            "maxmem",
            "disk",
            "maxdisk",
            "netin",
            "netout",
        )
        return {key: data.get(key) for key in allowed}

    def recent_tasks(self, node: str) -> Any:
        self._allow_node(node)
        tasks = self.client.request(
            "GET",
            f"nodes/{node}/tasks",
            params={"limit": 25},
        ) or []
        return [
            {
                key: item.get(key)
                for key in (
                    "upid",
                    "type",
                    "id",
                    "user",
                    "status",
                    "starttime",
                    "endtime",
                )
            }
            for item in tasks[:25]
            if item.get("id") is None
            or not str(item.get("id")).isdigit()
            or int(item["id"]) in self.settings.proxmox_allowed_guests
        ]

    def discover_guest(self, query: str) -> Any:
        query = query.strip().lower()
        if not query:
            raise ToolError("Guest search query cannot be empty")
        return [
            item
            for item in self._inventory()
            if query in str(item.get("vmid", "")).lower()
            or query in str(item.get("name", "")).lower()
        ][:20]

    def request_start_guest(
        self,
        node: str,
        guest_id: int,
        guest_type: str,
    ) -> dict[str, Any]:
        self._allow_guest_target(node, guest_id, guest_type)
        approval = self.approvals.create(
            "start_guest",
            {"node": node, "guest_id": guest_id, "guest_type": guest_type},
            f"Start {guest_type} guest {guest_id} on Proxmox node '{node}'",
        )
        return {"pending_approval": asdict(approval)}

    def request_reboot_guest(
        self,
        node: str,
        guest_id: int,
        guest_type: str,
    ) -> dict[str, Any]:
        self._allow_guest_target(node, guest_id, guest_type)
        approval = self.approvals.create(
            "reboot_guest",
            {"node": node, "guest_id": guest_id, "guest_type": guest_type},
            f"Reboot {guest_type} guest {guest_id} on Proxmox node '{node}'",
        )
        return {"pending_approval": asdict(approval)}

    def execute_approved(self, action: str, arguments: dict[str, Any]) -> Any:
        node = arguments["node"]
        guest_id = int(arguments["guest_id"])
        guest_type = arguments["guest_type"]
        self._allow_guest_target(node, guest_id, guest_type)
        operation = "start" if action == "start_guest" else "reboot"
        upid = self.client.request(
            "POST",
            f"nodes/{node}/{guest_type}/{guest_id}/status/{operation}",
        )
        return {"operation": operation, "upid": upid}
