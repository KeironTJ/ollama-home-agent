from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from ..core.config import Settings
from ..core.security import bounded_redacted
from ..integrations import CraftyClient
from ..services.approvals import ApprovalStore
from .base import ToolError, tool_schema

SAFE_ACTIONS = frozenset({"start_server", "stop_server", "restart_server"})


class CraftyToolSet:
    approved_actions = frozenset({"crafty_server_action"})

    def __init__(
        self,
        settings: Settings,
        client: CraftyClient,
        approvals: ApprovalStore,
    ):
        self.settings = settings
        self.client = client
        self.approvals = approvals

    @property
    def handlers(self) -> dict[str, Callable[..., Any]]:
        return {
            "crafty_list_servers": self.list_servers,
            "crafty_server_stats": self.server_stats,
            "crafty_server_logs": self.server_logs,
            "request_crafty_action": self.request_action,
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        if not self.client.configured:
            return []
        server_id = {
            "type": "string",
            "enum": sorted(self.settings.crafty_allowed_servers),
        }
        return [
            tool_schema(
                "crafty_list_servers",
                "List the allowlisted Minecraft servers managed by Crafty.",
                {},
                [],
            ),
            tool_schema(
                "crafty_server_stats",
                "Get runtime statistics for one allowlisted Crafty server.",
                {"server_id": server_id},
                ["server_id"],
            ),
            tool_schema(
                "crafty_server_logs",
                "Read bounded recent logs for one allowlisted Crafty server.",
                {"server_id": server_id},
                ["server_id"],
            ),
            tool_schema(
                "request_crafty_action",
                "Request approval to start, stop, or restart an allowlisted Crafty server.",
                {
                    "server_id": server_id,
                    "action": {
                        "type": "string",
                        "enum": sorted(SAFE_ACTIONS),
                    },
                },
                ["server_id", "action"],
            ),
        ]

    def _allow_server(self, server_id: str) -> None:
        if server_id not in self.settings.crafty_allowed_servers:
            raise ToolError(f"Crafty server '{server_id}' is not allowlisted")

    @staticmethod
    def _server_id(server: dict[str, Any]) -> str:
        return str(
            server.get("server_id")
            or server.get("server_uuid")
            or server.get("id")
            or ""
        )

    def list_servers(self) -> list[dict[str, Any]]:
        servers = self.client.request("GET", "servers") or []
        if isinstance(servers, dict):
            servers = servers.get("servers", [])
        if not isinstance(servers, list):
            raise ToolError("Crafty returned an unexpected server-list shape")
        allowed = set(self.settings.crafty_allowed_servers)
        return [
            {
                key: server.get(key)
                for key in (
                    "server_id",
                    "server_uuid",
                    "id",
                    "server_name",
                    "name",
                    "type",
                    "show_status",
                )
                if key in server
            }
            for server in servers
            if isinstance(server, dict) and self._server_id(server) in allowed
        ]

    def server_stats(self, server_id: str) -> Any:
        self._allow_server(server_id)
        data = self.client.request("GET", f"servers/{server_id}/stats") or {}
        if not isinstance(data, dict):
            raise ToolError("Crafty returned an unexpected statistics shape")
        allowed = (
            "server_id",
            "server_name",
            "running",
            "crashed",
            "updating",
            "waiting_start",
            "cpu",
            "mem",
            "mem_percent",
            "online",
            "max",
            "version",
            "started",
        )
        return {key: data.get(key) for key in allowed if key in data}

    def server_logs(self, server_id: str) -> Any:
        self._allow_server(server_id)
        result = self.client.request(
            "GET",
            f"servers/{server_id}/logs",
            params={
                "file": "false",
                "colors": "false",
                "raw": "false",
                "html": "false",
            },
        )
        return bounded_redacted(result, self.settings.max_tool_output_chars)

    def request_action(self, server_id: str, action: str) -> dict[str, Any]:
        self._allow_server(server_id)
        if action not in SAFE_ACTIONS:
            raise ToolError(f"Crafty action '{action}' is not permitted")
        approval = self.approvals.create(
            "crafty_server_action",
            {"server_id": server_id, "action": action},
            f"{action.replace('_', ' ').title()} for Crafty server '{server_id}'",
        )
        return {"pending_approval": asdict(approval)}

    def execute_approved(self, action: str, arguments: dict[str, Any]) -> Any:
        server_id = arguments["server_id"]
        server_action = arguments["action"]
        self._allow_server(server_id)
        if server_action not in SAFE_ACTIONS:
            raise ToolError(f"Crafty action '{server_action}' is not permitted")
        return self.client.request(
            "POST",
            f"servers/{server_id}/action/{server_action}",
            action=True,
        )
