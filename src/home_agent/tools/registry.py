from __future__ import annotations

from typing import Any, Callable

from ..core.config import Settings
from ..core.security import bounded_redacted
from ..integrations import ExternalServiceError, ProxmoxClient
from ..services.approvals import ApprovalStore
from ..services.audit import AuditLog
from .base import ToolError
from .proxmox import ProxmoxToolSet
from .ssh import SshToolSet


class DiagnosticTools:
    def __init__(
        self,
        settings: Settings,
        proxmox: ProxmoxClient,
        approvals: ApprovalStore,
        audit: AuditLog,
    ):
        self.settings = settings
        self.proxmox = proxmox
        self.audit = audit
        self.proxmox_tools = ProxmoxToolSet(settings, proxmox, approvals)
        self.ssh_tools = SshToolSet(settings, approvals)
        self._tool_sets = (self.proxmox_tools, self.ssh_tools)
        self._functions: dict[str, Callable[..., Any]] = {}
        for tool_set in self._tool_sets:
            self._functions.update(tool_set.handlers)

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [
            schema
            for tool_set in self._tool_sets
            for schema in tool_set.schemas
        ]

    def schemas_for(self, allowed_names: frozenset[str]) -> list[dict[str, Any]]:
        return [
            schema
            for schema in self.schemas
            if schema["function"]["name"] in allowed_names
        ]

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        session_id: str | None = None,
    ) -> Any:
        function = self._functions.get(name)
        if function is None:
            raise ToolError(f"Unknown tool: {name}")
        try:
            result = function(**arguments)
            safe = bounded_redacted(
                result,
                self.settings.max_tool_output_chars,
            )
            self.audit.record(
                "tool_call",
                session_id=session_id,
                name=name,
                input_data=arguments,
                output_data=safe,
                success=True,
            )
            return result
        except (ToolError, ExternalServiceError, ValueError, TypeError) as exc:
            self.audit.record(
                "tool_call",
                session_id=session_id,
                name=name,
                input_data=arguments,
                output_data=str(exc),
                success=False,
            )
            raise

    def execute_approved(self, action: str, arguments: dict[str, Any]) -> Any:
        for tool_set in self._tool_sets:
            if action in tool_set.approved_actions:
                return tool_set.execute_approved(action, arguments)
        raise ToolError(f"Unsupported approved action: {action}")
