from __future__ import annotations

from dataclasses import dataclass

from .core.config import Settings
from .integrations import CraftyClient, OllamaClient, ProxmoxClient
from .services.agent import AgentRunner
from .services.approvals import ApprovalStore
from .services.audit import AuditLog
from .services.coordinator import MasterCoordinator
from .services.history import ChatHistory
from .services.specialists import SpecialistRegistry
from .tools import DiagnosticTools


@dataclass(frozen=True)
class AppServices:
    settings: Settings
    audit: AuditLog
    history: ChatHistory
    approvals: ApprovalStore
    proxmox: ProxmoxClient
    crafty: CraftyClient
    ollama: OllamaClient
    tools: DiagnosticTools
    runner: AgentRunner
    coordinator: MasterCoordinator


def build_services(settings: Settings) -> AppServices:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(settings.database_path, settings.audit_max_output_chars)
    history = ChatHistory(settings.database_path)
    approvals = ApprovalStore(audit, settings.approval_ttl_seconds)
    proxmox = ProxmoxClient(settings)
    crafty = CraftyClient(settings)
    ollama = OllamaClient(settings)
    tools = DiagnosticTools(
        settings,
        proxmox,
        approvals,
        audit,
        crafty=crafty,
    )
    runner = AgentRunner(settings, ollama, tools, audit)
    coordinator = MasterCoordinator(runner, SpecialistRegistry(), audit)
    return AppServices(
        settings=settings,
        audit=audit,
        history=history,
        approvals=approvals,
        proxmox=proxmox,
        crafty=crafty,
        ollama=ollama,
        tools=tools,
        runner=runner,
        coordinator=coordinator,
    )
