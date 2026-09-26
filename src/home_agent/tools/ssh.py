from __future__ import annotations

import re
import socket
from dataclasses import asdict
from typing import Any, Callable

from ..core.config import Settings
from ..core.security import bounded_redacted
from ..services.approvals import ApprovalStore
from .base import ToolError, tool_schema

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.@-]+$")


class SshToolSet:
    approved_actions = frozenset({"restart_service"})

    def __init__(self, settings: Settings, approvals: ApprovalStore):
        self.settings = settings
        self.approvals = approvals

    @property
    def handlers(self) -> dict[str, Callable[..., Any]]:
        return {
            "ssh_service_status": self.service_status,
            "ssh_service_logs": self.service_logs,
            "ssh_system_resources": self.system_resources,
            "tcp_port_check": self.tcp_port_check,
            "request_restart_service": self.request_restart_service,
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        if not self.settings.ssh_hosts:
            return []
        host = {"type": "string", "enum": sorted(self.settings.ssh_hosts)}
        services = {
            item
            for target in self.settings.ssh_hosts.values()
            for item in target.get("services", [])
        }
        service = {"type": "string", "enum": sorted(services)}
        ports = {
            item
            for target in self.settings.ssh_hosts.values()
            for item in target.get("ports", [])
        }
        port = {"type": "integer", "enum": sorted(ports)}
        schemas = [
            tool_schema(
                "ssh_system_resources",
                "Read disk and memory summary from an allowlisted SSH host.",
                {"host": host},
                ["host"],
            ),
        ]
        if services:
            schemas.extend(
                [
                    tool_schema(
                        "ssh_service_status",
                        "Check a configured service on an allowlisted SSH host.",
                        {"host": host, "service": service},
                        ["host", "service"],
                    ),
                    tool_schema(
                        "ssh_service_logs",
                        "Read a bounded recent journal for an allowlisted service and host.",
                        {"host": host, "service": service},
                        ["host", "service"],
                    ),
                    tool_schema(
                        "request_restart_service",
                        "Request approval to restart an allowlisted service.",
                        {"host": host, "service": service},
                        ["host", "service"],
                    ),
                ]
            )
        if ports:
            schemas.append(
                tool_schema(
                    "tcp_port_check",
                    "Check one configured TCP port from this machine.",
                    {"host": host, "port": port},
                    ["host", "port"],
                )
            )
        return schemas

    def _target(
        self,
        host: str,
        service: str | None = None,
        port: int | None = None,
    ) -> dict[str, Any]:
        target = self.settings.ssh_hosts.get(host)
        if not isinstance(target, dict) or not target.get("hostname"):
            raise ToolError(f"SSH host '{host}' is not allowlisted")
        if service is not None:
            if (
                not SAFE_NAME.fullmatch(service)
                or service not in target.get("services", [])
            ):
                raise ToolError(
                    f"Service '{service}' is not allowlisted for host '{host}'"
                )
        if port is not None and port not in target.get("ports", []):
            raise ToolError(
                f"TCP port '{port}' is not allowlisted for host '{host}'"
            )
        return target

    def _run(self, host: str, command: str) -> dict[str, Any]:
        target = self._target(host)
        if not self.settings.ssh_key_file:
            raise ToolError("SSH key file is not configured")
        try:
            import paramiko
        except ImportError as exc:
            raise ToolError(
                'SSH support is not installed; run: pip install -e ".[ssh]"'
            ) from exc
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
            _, stdout, stderr = client.exec_command(
                command,
                timeout=self.settings.ssh_timeout_seconds,
            )
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode("utf-8", "replace")
            error = stderr.read().decode("utf-8", "replace")
        except Exception as exc:
            raise ToolError(
                f"Restricted SSH diagnostic failed for '{host}': {exc}"
            ) from exc
        finally:
            client.close()
        return {
            "exit_code": exit_code,
            "stdout": bounded_redacted(
                output,
                self.settings.max_tool_output_chars,
            ),
            "stderr": bounded_redacted(error, 2_000),
        }

    def service_status(self, host: str, service: str) -> Any:
        self._target(host, service=service)
        return self._run(
            host,
            f"systemctl --no-pager --full status {service}",
        )

    def service_logs(self, host: str, service: str) -> Any:
        self._target(host, service=service)
        return self._run(
            host,
            f"journalctl --no-pager -u {service} "
            f"-n {self.settings.ssh_log_lines} --output=short-iso",
        )

    def system_resources(self, host: str) -> Any:
        self._target(host)
        return self._run(
            host,
            "df -h --output=source,fstype,size,used,avail,pcent,target; free -h",
        )

    def tcp_port_check(self, host: str, port: int) -> Any:
        target = self._target(host, port=port)
        try:
            with socket.create_connection((target["hostname"], port), timeout=4):
                return {"host": host, "port": port, "reachable": True}
        except OSError as exc:
            return {
                "host": host,
                "port": port,
                "reachable": False,
                "error": str(exc),
            }

    def request_restart_service(
        self,
        host: str,
        service: str,
    ) -> dict[str, Any]:
        self._target(host, service=service)
        approval = self.approvals.create(
            "restart_service",
            {"host": host, "service": service},
            f"Restart service '{service}' on SSH host '{host}'",
        )
        return {"pending_approval": asdict(approval)}

    def execute_approved(self, action: str, arguments: dict[str, Any]) -> Any:
        host = arguments["host"]
        service = arguments["service"]
        self._target(host, service=service)
        return self._run(host, f"sudo -n systemctl restart {service}")
