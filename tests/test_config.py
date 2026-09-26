from home_agent.core.config import Settings


def test_csv_allowlists_parse_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("HOME_AGENT_PROXMOX_ALLOWED_NODES", "pve,node2")
    monkeypatch.setenv("HOME_AGENT_PROXMOX_ALLOWED_GUESTS", "100, 101")
    settings = Settings(_env_file=None)
    assert settings.proxmox_allowed_nodes == ("pve", "node2")
    assert settings.proxmox_allowed_guests == (100, 101)
