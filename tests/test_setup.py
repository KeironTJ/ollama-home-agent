import json
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from home_agent.app import create_app


def test_local_setup_saves_only_non_secret_configuration(settings) -> None:
    app = create_app(settings)
    client = TestClient(app, client=("127.0.0.1", 50000))
    setup = client.get("/api/setup")
    assert setup.status_code == 200
    assert "proxmox_token_secret" not in setup.json()

    response = client.put(
        "/api/setup",
        headers={"X-Home-Agent-Setup-Token": setup.json()["setup_token"]},
        json={
            "ollama_url": "http://127.0.0.1:11434",
            "ollama_model": "llama3.1:8b",
            "proxmox_url": "https://192.168.1.232:8006",
            "proxmox_token_id": "home-agent@pve!diagnostic",
            "proxmox_ca_file": "C:\\certs\\pve.pem",
            "proxmox_insecure_tls": False,
            "proxmox_allowed_nodes": ["pve"],
            "proxmox_allowed_guests": [100],
            "ssh_username": "diagnostic-agent",
            "ssh_key_file": "C:\\keys\\home-agent",
            "ssh_hosts": [
                {
                    "alias": "minecraft",
                    "hostname": "192.0.2.10",
                    "services": ["minecraft"],
                    "ports": [25565],
                }
            ],
        },
    )
    assert response.status_code == 200
    saved = json.loads(settings.config_file.read_text(encoding="utf-8"))
    assert saved["proxmox_allowed_guests"] == [100]
    assert '"minecraft"' in saved["ssh_hosts_json"]
    assert "proxmox_token_secret" not in saved


def test_setup_write_requires_csrf_token(settings) -> None:
    client = TestClient(create_app(settings), client=("127.0.0.1", 50000))
    response = client.put(
        "/api/setup",
        json={
            "ollama_url": "http://127.0.0.1:11434",
            "ollama_model": "llama3.1:8b",
            "proxmox_url": "https://192.168.1.232:8006",
        },
    )
    assert response.status_code == 403


def test_setup_rejects_user_id_without_api_token_name(settings) -> None:
    client = TestClient(create_app(settings), client=("127.0.0.1", 50000))
    setup_token = client.get("/api/setup").json()["setup_token"]
    response = client.put(
        "/api/setup",
        headers={"X-Home-Agent-Setup-Token": setup_token},
        json={
            "ollama_url": "http://127.0.0.1:11434",
            "ollama_model": "llama3.1:8b",
            "proxmox_url": "https://192.168.1.232:8006",
            "proxmox_token_id": "home-agent@pve",
        },
    )
    assert response.status_code == 400
    assert "!token-name" in response.json()["detail"]


def test_local_restart_requires_token_and_requests_graceful_shutdown(settings) -> None:
    app = create_app(settings)
    shutdown = Mock()
    app.state.shutdown_callback = shutdown
    client = TestClient(app, client=("127.0.0.1", 50000))
    setup_token = client.get("/api/setup").json()["setup_token"]

    assert client.post("/api/restart").status_code == 403
    timer = Mock()
    timer.daemon = False
    with patch("home_agent.routers.setup.threading.Timer", return_value=timer):
        response = client.post(
            "/api/restart",
            headers={"X-Home-Agent-Setup-Token": setup_token},
        )
    assert response.status_code == 200
    assert app.state.restart_requested is True
    timer.start.assert_called_once()
