from __future__ import annotations

import json
import re
import socket
from dataclasses import asdict
from typing import Any, Callable

from .approvals import ApprovalStore, PendingApproval
from .audit import AuditLog
from .clients import ExternalServiceError, ProxmoxClient
from .config import Settings
from .security import bounded_redacted

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.@-]+$")


class ToolError(RuntimeError):
    pass


def tool_schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


class DiagnosticTools:
    def __init__(self, settings: Settings, proxmox: ProxmoxClient, approvals: ApprovalStore, audit: AuditLog):
        self.settings = settings
        self.proxmox = proxmox
        self.approvals = approvals
        self.audit = audit
        self._functions: dict[str, Callable[..., Any]] = {
            "proxmox_inventory": self.proxmox_inventory,
            "proxmox_node_status": self.proxmox_node_status,
            "proxmox_guest_status": self.proxmox_guest_status,
            "proxmox_recent_tasks": self.proxmox_recent_tasks,
            "discover_guest": self.discover_guest,
            "ssh_service_status": self.ssh_service_status,
            "ssh_service_logs": self.ssh_service_logs,
            "ssh_system_resources": self.ssh_system_resources,
            "tcp_port_check": self.tcp_port_check,
            "request_restart_service": self.request_restart_service,
            "request_start_guest": self.request_start_guest,
            "request_reboot_guest": self.request_reboot_guest,
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        string = {"type": "string"}
        integer = {"type": "integer"}
        return [
            tool_schema("proxmox_inventory", "List allowlisted Proxmox nodes and guests.", {}, []),
            tool_schema("proxmox_node_status", "Get status for one allowlisted node.", {"node": string}, ["node"]),
            tool_schema(
                "proxmox_guest_status",
                "Get current status for one allowlisted VM or LXC.",
                {"node": string, "guest_id": integer, "guest_type": {"type": "string", "enum": ["qemu", "lxc"]}},
                ["node", "guest_id", "guest_type"],
            ),
            tool_schema("proxmox_recent_tasks", "List recent tasks on an allowlisted node.", {"node": string}, ["node"]),
            tool_schema("discover_guest", "Find allowlisted guests by name or numeric ID.", {"query": string}, ["query"]),
            tool_schema(
                "ssh_service_status",
                "Check a configured service on an allowlisted SSH host.",
                {"host": string, "service": string},
                ["host", "service"],
            ),
            tool_schema(
                "ssh_service_logs",
                "Read a bounded recent journal for a configured service on an allowlisted SSH host.",
                {"host": string, "service": string},
                ["host", "service"],
            ),
            tool_schema("ssh_system_resources", "Read disk and memory summary from an allowlisted SSH host.", {"host": string}, ["host"]),
            tool_schema(
                "tcp_port_check",
                "Check one configured TCP port from this machine.",
                {"host": string, "port": integer},
                ["host", "port"],
            ),
            tool_schema(
                "request_restart_service",
                "Request explicit user approval to restart an allowlisted service. Never restarts immediately.",
                {"host": string, "service": string},
                ["host", "service"],
            ),
            tool_schema(
                "request_start_guest",
                "Request explicit user approval to start an allowlisted Proxmox guest.",
                {"node": string, "guest_id": integer, "guest_type": {"type": "string", "enum": ["qemu", "lxc"]}},
                ["node", "guest_id", "guest_type"],
            ),
            tool_schema(
                "request_reboot_guest",
                "Request explicit user approval to reboot an allowlisted Proxmox guest.",
                {"node": string, "guest_id": integer, "guest_type": {"type": "string", "enum": ["qemu", "lxc"]}},
                ["node", "guest_id", "guest_type"],
            ),
        ]

    def invoke(self, name: str, arguments: dict[str, Any], session_id: str | None = None) -> Any:
        function = self._functions.get(name)
        if function is None:
            raise ToolError(f"Unknown tool: {name}")
        try:
            result = function(**arguments)
            safe = bounded_redacted(result, self.settings.max_tool_output_chars)
            self.audit.record("tool_call", session_id=session_id, name=name, input_data=arguments, output_data=safe, success=True)
            return result
        except (ToolError, ExternalServiceError, ValueError, TypeError) as exc:
            self.audit.record("tool_call", session_id=session_id, name=name, input_data=arguments, output_data=str(exc), success=False)
            raise

    def _allow_node(self, node: str) -> None:
        if node not in self.settings.proxmox_allowed_nodes:
            raise ToolError(f"Proxmox node '{node}' is not allowlisted")

    def _allow_guest(self, guest_id: int) -> None:
        if guest_id not in self.settings.proxmox_allowed_guests:
            raise ToolError(f"Proxmox guest '{guest_id}' is not allowlisted")

    def _allow_guest_target(self, node: str, guest_id: int, guest_type: str) -> None:
        self._allow_node(node)
        self._allow_guest(guest_id)
        if guest_type not in ("qemu", "lxc"):
            raise ToolError("guest_type must be qemu or lxc")

    def _ssh_target(self, host: str, service: str | None = None, port: int | None = None) -> dict[str, Any]:
        target = self.settings.ssh_hosts.get(host)
        if not isinstance(target, dict) or not target.get("hostname"):
            raise ToolError(f"SSH host '{host}' is not allowlisted")
        if service is not None:
            if not SAFE_NAME.fullmatch(service) or service not in target.get("services", []):
                raise ToolError(f"Service '{service}' is not allowlisted for host '{host}'")
        if port is not None and port not in target.get("ports", []):
            raise ToolError(f"TCP port '{port}' is not allowlisted for host '{host}'")
        return target

    def _inventory(self) -> list[dict[str, Any]]:
        resources = self.proxmox.request("GET", "cluster/resources", params={"type": "vm"}) or []
        return [
            {
                key: item.get(key)
                for key in ("vmid", "name", "type", "node", "status", "uptime", "cpu", "mem", "maxmem")
            }
            for item in resources
            if item.get("vmid") in self.settings.proxmox_allowed_guests
            and item.get("node") in self.settings.proxmox_allowed_nodes
        ]

    def proxmox_inventory(self) -> dict[str, Any]:
        nodes = self.proxmox.request("GET", "nodes") or []
        safe_nodes = [
            {key: item.get(key) for key in ("node", "status", "uptime", "cpu", "mem", "maxmem")}
            for item in nodes
            if item.get("node") in self.settings.proxmox_allowed_nodes
        ]
        return {"nodes": safe_nodes, "guests": self._inventory()}

    def proxmox_node_status(self, node: str) -> Any:
        self._allow_node(node)
        data = self.proxmox.request("GET", f"nodes/{node}/status") or {}
        allowed = ("uptime", "loadavg", "cpu", "memory", "swap", "rootfs", "pveversion", "kversion")
        return {key: data.get(key) for key in allowed}

    def proxmox_guest_status(self, node: str, guest_id: int, guest_type: str) -> Any:
        self._allow_guest_target(node, guest_id, guest_type)
        data = self.proxmox.request("GET", f"nodes/{node}/{guest_type}/{guest_id}/status/current") or {}
        allowed = ("vmid", "name", "status", "uptime", "cpu", "cpus", "mem", "maxmem", "disk", "maxdisk", "netin", "netout")
        return {key: data.get(key) for key in allowed}

    def proxmox_recent_tasks(self, node: str) -> Any:
        self._allow_node(node)
        tasks = self.proxmox.request("GET", f"nodes/{node}/tasks", params={"limit": 25}) or []
        return [
            {key: item.get(key) for key in ("upid", "type", "id", "user", "status", "starttime", "endtime")}
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
            if query in str(item.get("vmid", "")).lower() or query in str(item.get("name", "")).lower()
        ][:20]

    def _ssh_run(self, host: str, command: str) -> dict[str, Any]:
        target = self._ssh_target(host)
        if not self.settings.ssh_key_file:
            raise ToolError("SSH key file is not configured")
        try:
            import paramiko
        except ImportError as exc:
            raise ToolError("SSH support is not installed; run: pip install -e \".[ssh]\"") from exc
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(
                hostname=target["hostname"],
                port=int(target.get("ssh_port", 22)),
                username=self.settings.ssh_username,
                key_filename=str(self.settings.ssh_key_file),
                timeout=self.settings.ssh_timeout_seconds,
                allow_agent=False,
                look_for_keys=False,
            )
            _, stdout, stderr = client.exec_command(command, timeout=self.settings.ssh_timeout_seconds)
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode("utf-8", "replace")
            error = stderr.read().decode("utf-8", "replace")
        except Exception as exc:
            raise ToolError(f"Restricted SSH diagnostic failed for '{host}': {exc}") from exc
        finally:
            client.close()
        return {
            "exit_code": exit_code,
            "stdout": bounded_redacted(output, self.settings.max_tool_output_chars),
            "stderr": bounded_redacted(error, 2_000),
        }

    def ssh_service_status(self, host: str, service: str) -> Any:
        self._ssh_target(host, service=service)
        return self._ssh_run(host, f"systemctl --no-pager --full status {service}")

    def ssh_service_logs(self, host: str, service: str) -> Any:
        self._ssh_target(host, service=service)
        return self._ssh_run(
            host,
            f"journalctl --no-pager -u {service} -n {self.settings.ssh_log_lines} --output=short-iso",
        )

    def ssh_system_resources(self, host: str) -> Any:
        self._ssh_target(host)
        return self._ssh_run(host, "df -h --output=source,fstype,size,used,avail,pcent,target; free -h")

    def tcp_port_check(self, host: str, port: int) -> Any:
        target = self._ssh_target(host, port=port)
        try:
            with socket.create_connection((target["hostname"], port), timeout=4):
                return {"host": host, "port": port, "reachable": True}
        except OSError as exc:
            return {"host": host, "port": port, "reachable": False, "error": str(exc)}

    def request_restart_service(self, host: str, service: str) -> dict[str, Any]:
        self._ssh_target(host, service=service)
        approval = self.approvals.create(
            "restart_service",
            {"host": host, "service": service},
            f"Restart service '{service}' on SSH host '{host}'",
        )
        return {"pending_approval": asdict(approval)}

    def request_start_guest(self, node: str, guest_id: int, guest_type: str) -> dict[str, Any]:
        self._allow_guest_target(node, guest_id, guest_type)
        approval = self.approvals.create(
            "start_guest",
            {"node": node, "guest_id": guest_id, "guest_type": guest_type},
            f"Start {guest_type} guest {guest_id} on Proxmox node '{node}'",
        )
        return {"pending_approval": asdict(approval)}

    def request_reboot_guest(self, node: str, guest_id: int, guest_type: str) -> dict[str, Any]:
        self._allow_guest_target(node, guest_id, guest_type)
        approval = self.approvals.create(
            "reboot_guest",
            {"node": node, "guest_id": guest_id, "guest_type": guest_type},
            f"Reboot {guest_type} guest {guest_id} on Proxmox node '{node}'",
        )
        return {"pending_approval": asdict(approval)}

    def execute_approved(self, action: str, arguments: dict[str, Any]) -> Any:
        if action == "restart_service":
            host, service = arguments["host"], arguments["service"]
            self._ssh_target(host, service=service)
            return self._ssh_run(host, f"sudo -n systemctl restart {service}")
        if action in ("start_guest", "reboot_guest"):
            node = arguments["node"]
            guest_id = int(arguments["guest_id"])
            guest_type = arguments["guest_type"]
            self._allow_guest_target(node, guest_id, guest_type)
            operation = "start" if action == "start_guest" else "reboot"
            upid = self.proxmox.request(
                "POST",
                f"nodes/{node}/{guest_type}/{guest_id}/status/{operation}",
            )
            return {"operation": operation, "upid": upid}
        raise ToolError(f"Unsupported approved action: {action}")

