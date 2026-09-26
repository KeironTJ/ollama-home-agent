from unittest.mock import Mock, patch

import httpx
import pytest

from home_agent.integrations import ExternalServiceError, OllamaClient, ProxmoxClient
from home_agent.services.agent import AgentRunner
from home_agent.tools import DiagnosticTools


def test_proxmox_uses_json_api_and_token(settings) -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": {"status": "ok"}}
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.request.return_value = response

    with patch("home_agent.integrations.proxmox.httpx.Client", return_value=client):
        result = ProxmoxClient(settings).request("GET", "nodes/pve/status")

    assert result == {"status": "ok"}
    args, kwargs = client.request.call_args
    assert args[:2] == ("GET", "https://192.168.1.232:8006/api2/json/nodes/pve/status")
    assert kwargs["headers"]["Authorization"].startswith("PVEAPIToken=test@pve!agent=")


def test_proxmox_rejects_user_identity_without_token_name(settings) -> None:
    settings.proxmox_token_id = "test@pve"
    client = ProxmoxClient(settings)
    assert client.configured is False
    with pytest.raises(ExternalServiceError, match="user@realm!token-name"):
        client.request("GET", "version")


def test_ollama_unavailable_has_useful_error(settings) -> None:
    with patch(
        "home_agent.integrations.ollama.httpx.Client.post",
        side_effect=httpx.ConnectError("refused"),
    ):
        with pytest.raises(ExternalServiceError, match="ollama serve"):
            OllamaClient(settings).chat([], [])


def test_proxmox_tls_failure_is_not_reported_as_unreachable(settings) -> None:
    with patch(
        "home_agent.integrations.proxmox.httpx.Client.request",
        side_effect=httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"),
    ):
        with pytest.raises(ExternalServiceError, match="TLS verification failed"):
            ProxmoxClient(settings).request("GET", "version")


def test_agent_runs_mocked_tool_loop(settings, approvals, audit) -> None:
    proxmox = Mock()
    proxmox.request.return_value = {"status": "running", "vmid": 100}
    tools = DiagnosticTools(settings, proxmox, approvals, audit)
    ollama = Mock()
    ollama.chat.side_effect = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "proxmox_guest_status",
                        "arguments": {"node": "pve", "guest_id": 100, "guest_type": "qemu"},
                    }
                }
            ],
        },
        {"role": "assistant", "content": "Guest 100 is running."},
    ]

    result = AgentRunner(settings, ollama, tools, audit).run("Check Minecraft", "session")
    assert result["message"] == "Guest 100 is running."
    assert ollama.chat.call_count == 2
    proxmox.request.assert_called_once()


def test_agent_does_not_substitute_ssh_when_proxmox_is_unconfigured(
    settings, approvals, audit
) -> None:
    settings.proxmox_token_id = "test@pve"
    proxmox = ProxmoxClient(settings)
    tools = DiagnosticTools(settings, proxmox, approvals, audit)
    ollama = Mock()

    result = AgentRunner(settings, ollama, tools, audit).run(
        "Check my Proxmox guest status",
        "session",
    )

    assert "token ID is incomplete" in result["message"]
    assert "did not substitute SSH" in result["message"]
    ollama.chat.assert_not_called()
