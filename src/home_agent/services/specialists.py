from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpecialistDefinition:
    id: str
    name: str
    description: str
    instructions: str
    tool_names: frozenset[str]
    keywords: tuple[str, ...]


PROXMOX_TOOLS = frozenset(
    {
        "proxmox_inventory",
        "proxmox_node_status",
        "proxmox_guest_status",
        "proxmox_recent_tasks",
        "discover_guest",
        "request_start_guest",
        "request_reboot_guest",
    }
)
SSH_TOOLS = frozenset(
    {
        "ssh_service_status",
        "ssh_service_logs",
        "ssh_system_resources",
        "tcp_port_check",
        "request_restart_service",
    }
)
CRAFTY_TOOLS = frozenset(
    {
        "crafty_list_servers",
        "crafty_server_stats",
        "crafty_server_logs",
        "request_crafty_action",
    }
)


class SpecialistRegistry:
    def __init__(self) -> None:
        specialists = (
            SpecialistDefinition(
                id="minecraft",
                name="Minecraft specialist",
                description="Guest, service, log, resource, and port diagnostics.",
                instructions=(
                    "Diagnose Minecraft from the outside in: first establish guest state, "
                    "then TCP reachability, service state, resources, and bounded logs. "
                    "Do not conclude that Minecraft is healthy merely because its guest runs."
                ),
                tool_names=PROXMOX_TOOLS | CRAFTY_TOOLS | SSH_TOOLS,
                keywords=(
                    "minecraft",
                    "25565",
                    "java server",
                    "players cannot connect",
                    "game server",
                ),
            ),
            SpecialistDefinition(
                id="network",
                name="Network specialist",
                description="Allowlisted reachability and port diagnostics.",
                instructions=(
                    "Focus on observable network reachability. Distinguish DNS, host, "
                    "port, and application-level hypotheses and do not invent scans."
                ),
                tool_names=frozenset({"tcp_port_check", "proxmox_inventory"}),
                keywords=(
                    "port",
                    "network",
                    "connection",
                    "connect",
                    "reachable",
                    "timeout",
                ),
            ),
            SpecialistDefinition(
                id="proxmox",
                name="Proxmox specialist",
                description="Node, VM, LXC, inventory, and task diagnostics.",
                instructions=(
                    "Focus on Proxmox inventory, node health, guest state, and recent "
                    "tasks. Treat running guest state as distinct from application health."
                ),
                tool_names=PROXMOX_TOOLS,
                keywords=(
                    "proxmox",
                    " pve",
                    "virtual machine",
                    " vm",
                    "lxc",
                    "guest",
                    "node",
                    "container",
                ),
            ),
            SpecialistDefinition(
                id="general",
                name="Home diagnostics",
                description="General allowlisted home-server investigation.",
                instructions=(
                    "Triage the request with the least invasive available diagnostic "
                    "tools and clearly state any missing integration."
                ),
                tool_names=PROXMOX_TOOLS | CRAFTY_TOOLS | SSH_TOOLS,
                keywords=(),
            ),
        )
        self._specialists = {item.id: item for item in specialists}

    def route(self, query: str) -> SpecialistDefinition:
        normalized = f" {query.lower()} "
        candidates = [
            specialist
            for specialist in self._specialists.values()
            if specialist.id != "general"
        ]
        scored = [
            (
                sum(
                    3 if keyword.strip() == "minecraft" else 1
                    for keyword in specialist.keywords
                    if keyword in normalized
                ),
                specialist,
            )
            for specialist in candidates
        ]
        score, selected = max(scored, key=lambda item: item[0])
        return selected if score > 0 else self._specialists["general"]

    def get(self, specialist_id: str) -> SpecialistDefinition:
        return self._specialists[specialist_id]

    def list(self) -> list[SpecialistDefinition]:
        return list(self._specialists.values())
