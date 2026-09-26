from __future__ import annotations

from typing import Any

from .agent import AgentRunner
from .audit import AuditLog
from .specialists import SpecialistRegistry


class MasterCoordinator:
    def __init__(
        self,
        runner: AgentRunner,
        specialists: SpecialistRegistry,
        audit: AuditLog,
    ):
        self.runner = runner
        self.specialists = specialists
        self.audit = audit

    def run(self, user_message: str, session_id: str) -> dict[str, Any]:
        specialist = self.specialists.route(user_message)
        self.audit.record(
            "agent_routed",
            session_id=session_id,
            name=specialist.id,
            input_data=user_message,
            output_data={"specialist": specialist.name},
            success=True,
        )
        result = self.runner.run(
            user_message,
            session_id,
            specialist=specialist,
        )
        routing_artifact = {
            "type": "routing",
            "source": "master_coordinator",
            "data": {
                "id": specialist.id,
                "name": specialist.name,
                "description": specialist.description,
            },
        }
        result["artifacts"] = [routing_artifact, *result.get("artifacts", [])]
        result["specialist"] = {
            "id": specialist.id,
            "name": specialist.name,
        }
        return result
