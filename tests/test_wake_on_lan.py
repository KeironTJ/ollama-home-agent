from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from home_agent.app import create_app
from home_agent.core.config import Settings
from home_agent.integrations import (
    ExternalServiceError,
    OllamaClient,
    build_magic_packet,
    send_magic_packet,
)


def test_magic_packet_contains_only_configured_mac() -> None:
    packet = build_magic_packet("aa-bb-cc-dd-ee-ff")

    assert packet == b"\xff" * 6 + bytes.fromhex("AABBCCDDEEFF") * 16
    assert len(packet) == 102


def test_magic_packet_is_sent_to_configured_broadcast() -> None:
    client = Mock()
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=False)

    with patch(
        "home_agent.integrations.wake_on_lan.socket.socket",
        return_value=context,
    ):
        send_magic_packet("AA:BB:CC:DD:EE:FF", "192.168.1.255", 9)

    client.setsockopt.assert_called_once()
    client.sendto.assert_called_once_with(
        b"\xff" * 6 + bytes.fromhex("AABBCCDDEEFF") * 16,
        ("192.168.1.255", 9),
    )


def test_invalid_wake_configuration_is_rejected(tmp_path) -> None:
    with pytest.raises(ValidationError, match="MAC address"):
        Settings(
            data_dir=tmp_path,
            ollama_wol_enabled=True,
            ollama_wol_mac="not-a-mac",
        )

    with pytest.raises(ValidationError, match="IPv4"):
        Settings(
            data_dir=tmp_path,
            ollama_wol_broadcast="example.invalid",
        )


def test_ready_ollama_is_not_woken(settings) -> None:
    wake_sender = Mock()
    client = OllamaClient(settings, wake_sender=wake_sender)
    client.health = Mock(return_value={"ok": True})

    result = client.ensure_ready()

    assert result == {"ready": True, "wake_sent": False, "attempts": 0}
    wake_sender.assert_not_called()


def test_offline_ollama_is_woken_and_polled(settings) -> None:
    settings.ollama_device_name = "AI laptop"
    settings.ollama_wol_enabled = True
    settings.ollama_wol_mac = "AA:BB:CC:DD:EE:FF"
    settings.ollama_wol_broadcast = "192.168.1.255"
    settings.ollama_wake_poll_seconds = 0.5
    wake_sender = Mock()
    client = OllamaClient(settings, wake_sender=wake_sender)
    client.health = Mock(side_effect=[{"ok": False}, {"ok": True}])

    with patch("home_agent.integrations.ollama.time.sleep"):
        result = client.ensure_ready()

    assert result == {"ready": True, "wake_sent": True, "attempts": 1}
    wake_sender.assert_called_once_with(
        "AA:BB:CC:DD:EE:FF",
        "192.168.1.255",
        9,
    )


def test_wake_timeout_is_reported(settings) -> None:
    settings.ollama_device_name = "AI laptop"
    settings.ollama_wol_enabled = True
    settings.ollama_wol_mac = "AA:BB:CC:DD:EE:FF"
    settings.ollama_wake_timeout_seconds = 10
    client = OllamaClient(settings, wake_sender=Mock())
    client.health = Mock(return_value={"ok": False})

    with patch(
        "home_agent.integrations.ollama.time.monotonic",
        side_effect=[0, 11],
    ):
        with pytest.raises(ExternalServiceError, match="did not become ready"):
            client.ensure_ready()


def test_health_reports_configured_sleeping_device_as_standby(settings) -> None:
    settings.ollama_wol_enabled = True
    settings.ollama_wol_mac = "AA:BB:CC:DD:EE:FF"
    app = create_app(settings)
    app.state.services.ollama.health = Mock(
        return_value={
            "ok": False,
            "state": "standby",
            "device": "AI laptop",
            "wake_enabled": True,
            "error": "offline",
        }
    )
    app.state.services.crafty.health = Mock(
        return_value={"ok": False, "configured": False}
    )

    response = TestClient(
        app,
        client=("127.0.0.1", 50000),
    ).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "standby"
