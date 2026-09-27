from fastapi.testclient import TestClient

from home_agent.app import create_app
from home_agent.dependencies import ADMIN_FAILURE_LIMIT

PASSWORD = "correct-horse-battery"


def lan_client(settings, address: str) -> TestClient:
    return TestClient(create_app(settings), client=(address, 50000))


def test_remote_setup_disabled_without_admin_password(settings) -> None:
    settings.host = "0.0.0.0"
    client = lan_client(settings, "192.0.2.50")
    response = client.get("/api/setup")
    assert response.status_code == 403
    assert "HOME_AGENT_ADMIN_PASSWORD" in response.json()["detail"]


def test_loopback_requires_password_when_bound_to_lan(settings) -> None:
    settings.host = "0.0.0.0"
    client = lan_client(settings, "127.0.0.1")
    assert client.get("/api/setup").status_code == 403


def test_short_admin_password_is_rejected(settings) -> None:
    settings.host = "0.0.0.0"
    settings.admin_password = "short"
    client = lan_client(settings, "192.0.2.51")
    response = client.get(
        "/api/setup", headers={"X-Home-Agent-Admin-Password": "short"}
    )
    assert response.status_code == 403
    assert "at least" in response.json()["detail"]


def test_remote_setup_with_admin_password(settings) -> None:
    settings.host = "0.0.0.0"
    settings.admin_password = PASSWORD
    client = lan_client(settings, "192.0.2.52")

    assert client.get("/api/setup").status_code == 401
    assert (
        client.get(
            "/api/setup", headers={"X-Home-Agent-Admin-Password": "wrong-password-x"}
        ).status_code
        == 401
    )
    setup = client.get("/api/setup", headers={"X-Home-Agent-Admin-Password": PASSWORD})
    assert setup.status_code == 200
    assert PASSWORD not in setup.text

    body = {
        "ollama_url": "http://192.0.2.60:11434",
        "ollama_model": "llama3.1:8b",
        "proxmox_url": "https://192.168.1.232:8006",
    }
    token = setup.json()["setup_token"]
    no_password = client.put(
        "/api/setup", headers={"X-Home-Agent-Setup-Token": token}, json=body
    )
    assert no_password.status_code == 401
    saved = client.put(
        "/api/setup",
        headers={
            "X-Home-Agent-Setup-Token": token,
            "X-Home-Agent-Admin-Password": PASSWORD,
        },
        json=body,
    )
    assert saved.status_code == 200
    assert PASSWORD not in settings.config_file.read_text(encoding="utf-8")


def test_repeated_failures_lock_out_client(settings) -> None:
    settings.host = "0.0.0.0"
    settings.admin_password = PASSWORD
    client = lan_client(settings, "192.0.2.53")
    for _ in range(ADMIN_FAILURE_LIMIT):
        client.get("/api/setup", headers={"X-Home-Agent-Admin-Password": "nope-nope-nope"})
    locked = client.get("/api/setup", headers={"X-Home-Agent-Admin-Password": PASSWORD})
    assert locked.status_code == 429

    other = lan_client(settings, "192.0.2.54")
    assert (
        other.get("/api/setup", headers={"X-Home-Agent-Admin-Password": PASSWORD}).status_code
        == 200
    )
