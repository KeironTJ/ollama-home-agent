from unittest.mock import Mock

from home_agent.services.agent import AgentRunner
from home_agent.services.coordinator import MasterCoordinator
from home_agent.services.specialists import SpecialistRegistry
from home_agent.tools import DiagnosticTools


def test_registry_routes_queries_to_fixed_specialists() -> None:
    registry = SpecialistRegistry()
    assert registry.route("My Minecraft server is down").id == "minecraft"
    assert registry.route("Check Proxmox guest status").id == "proxmox"
    assert registry.route("Is port 25566 reachable?").id == "network"
    assert registry.route("What should I investigate?").id == "general"


def test_coordinator_passes_selected_specialist_and_returns_metadata(audit) -> None:
    runner = Mock()
    runner.run.return_value = {
        "message": "Checked.",
        "pending_approval": None,
        "artifacts": [],
    }
    coordinator = MasterCoordinator(runner, SpecialistRegistry(), audit)

    result = coordinator.run("Minecraft is unavailable", "session")

    specialist = runner.run.call_args.kwargs["specialist"]
    assert specialist.id == "minecraft"
    assert result["specialist"]["name"] == "Minecraft specialist"
    assert result["artifacts"][0]["type"] == "routing"


def test_specialist_only_exposes_its_allowed_tools(settings, approvals, audit) -> None:
    proxmox = Mock()
    proxmox.configured = True
    tools = DiagnosticTools(settings, proxmox, approvals, audit)
    ollama = Mock()
    ollama.chat.return_value = {"role": "assistant", "content": "Done."}
    runner = AgentRunner(settings, ollama, tools, audit)

    runner.run(
        "Check network connectivity",
        "session",
        specialist=SpecialistRegistry().get("network"),
    )

    schemas = ollama.chat.call_args.args[1]
    names = {schema["function"]["name"] for schema in schemas}
    assert names <= {"tcp_port_check", "proxmox_inventory"}
