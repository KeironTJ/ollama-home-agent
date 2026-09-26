from unittest.mock import Mock, patch

import pytest

from home_agent.core.config import Settings
from home_agent.integrations import CraftyClient, ExternalServiceError
from home_agent.tools import DiagnosticTools, ToolError


def crafty_settings(settings: Settings) -> Settings:
    settings.crafty_url = "https://192.0.2.20:8443"
    settings.crafty_read_token = "read-token"
    settings.crafty_action_token = "action-token"
    settings.crafty_allowed_servers = ("server-one", "server-two")
    return settings


def test_crafty_client_uses_bearer_token(settings) -> None:
    settings = crafty_settings(settings)
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"status": "ok", "data": {"running": True}}
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.request.return_value = response

    with patch("home_agent.integrations.crafty.httpx.Client", return_value=client):
        result = CraftyClient(settings).request(
            "GET",
            "servers/server-one/stats",
        )

    assert result == {"running": True}
    assert client.request.call_args.kwargs["headers"] == {
        "Authorization": "Bearer read-token"
    }


def test_crafty_health_uses_public_check_without_token(settings) -> None:
    settings.crafty_url = "https://192.0.2.20:8443"
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"status": "ok"}
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.request.return_value = response

    with patch("home_agent.integrations.crafty.httpx.Client", return_value=client):
        result = CraftyClient(settings).health()

    assert result == {"ok": True, "configured": True}
    assert client.request.call_args.kwargs["headers"] == {}


def test_crafty_tools_filter_servers_and_gate_actions(
    settings,
    approvals,
    audit,
) -> None:
    settings = crafty_settings(settings)
    crafty = Mock()
    crafty.configured = True
    crafty.request.return_value = [
        {"server_id": "server-one", "server_name": "Survival"},
        {"server_id": "not-allowed", "server_name": "Private"},
    ]
    tools = DiagnosticTools(
        settings,
        Mock(configured=True),
        approvals,
        audit,
        crafty=crafty,
    )

    servers = tools.invoke("crafty_list_servers", {})
    assert [server["server_id"] for server in servers] == ["server-one"]
    with pytest.raises(ToolError, match="not allowlisted"):
        tools.invoke(
            "crafty_server_stats",
            {"server_id": "not-allowed"},
        )

    pending = tools.invoke(
        "request_crafty_action",
        {"server_id": "server-one", "action": "restart_server"},
    )
    assert pending["pending_approval"]["status"] == "pending"
    crafty.request.assert_called_once()


def test_crafty_action_requires_separate_action_token(settings) -> None:
    settings = crafty_settings(settings)
    settings.crafty_action_token = ""
    with pytest.raises(ExternalServiceError, match="action API token"):
        CraftyClient(settings).request(
            "POST",
            "servers/server-one/action/restart_server",
            action=True,
        )
