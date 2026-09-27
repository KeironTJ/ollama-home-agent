from __future__ import annotations

import json
import threading
from ipaddress import IPv4Address
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import Services, require_local_request, require_setup_token
from ..core.config import normalize_mac_address
from ..integrations import ExternalServiceError
from ..schemas import SetupConfig

router = APIRouter(prefix="/api", tags=["setup"])
LocalRequest = Annotated[None, Depends(require_local_request)]
AuthorizedSetup = Annotated[None, Depends(require_setup_token)]


@router.get("/setup")
def get_setup(
    request: Request,
    services: Services,
    _local: LocalRequest,
) -> dict[str, Any]:
    settings = services.settings
    return {
        "setup_token": request.app.state.setup_token,
        "ollama_url": settings.ollama_url,
        "ollama_model": settings.ollama_model,
        "ollama_device_name": settings.ollama_device_name,
        "ollama_wol_enabled": settings.ollama_wol_enabled,
        "ollama_wol_mac": settings.ollama_wol_mac,
        "ollama_wol_broadcast": settings.ollama_wol_broadcast,
        "ollama_wol_port": settings.ollama_wol_port,
        "ollama_wake_timeout_seconds": settings.ollama_wake_timeout_seconds,
        "proxmox_url": settings.proxmox_url,
        "proxmox_token_id": settings.proxmox_token_id,
        "proxmox_token_secret_configured": bool(settings.proxmox_token_secret),
        "proxmox_ca_file": str(settings.proxmox_ca_file or ""),
        "proxmox_insecure_tls": settings.proxmox_insecure_tls,
        "proxmox_allowed_nodes": list(settings.proxmox_allowed_nodes),
        "proxmox_allowed_guests": list(settings.proxmox_allowed_guests),
        "crafty_url": settings.crafty_url,
        "crafty_ca_file": str(settings.crafty_ca_file or ""),
        "crafty_insecure_tls": settings.crafty_insecure_tls,
        "crafty_allowed_servers": list(settings.crafty_allowed_servers),
        "crafty_read_token_configured": bool(settings.crafty_read_token),
        "crafty_action_token_configured": bool(settings.crafty_action_token),
        "ssh_username": settings.ssh_username,
        "ssh_key_file": str(settings.ssh_key_file or ""),
        "ssh_hosts": [
            {
                "alias": alias,
                "hostname": target.get("hostname", ""),
                "services": target.get("services", []),
                "ports": target.get("ports", []),
                "ssh_port": target.get("ssh_port", 22),
            }
            for alias, target in settings.ssh_hosts.items()
        ],
        "config_file": str(settings.config_file or ""),
        "restart_available": request.app.state.shutdown_callback is not None,
    }


@router.put("/setup")
def save_setup(
    body: SetupConfig,
    services: Services,
    _authorized: AuthorizedSetup,
) -> dict[str, Any]:
    settings = services.settings
    if not body.proxmox_url.lower().startswith("https://"):
        raise HTTPException(status_code=400, detail="Proxmox URL must use HTTPS")
    if body.proxmox_token_id and "!" not in body.proxmox_token_id:
        raise HTTPException(
            status_code=400,
            detail="Proxmox API token ID must include '!token-name', for example user@pve!diagnostic",
        )
    if not body.ollama_url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Ollama URL must use HTTP or HTTPS")
    try:
        wol_mac = normalize_mac_address(body.ollama_wol_mac)
        wol_broadcast = str(IPv4Address(body.ollama_wol_broadcast.strip()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.ollama_wol_enabled and not wol_mac:
        raise HTTPException(
            status_code=400,
            detail="Wake-on-LAN requires a configured MAC address",
        )
    if body.crafty_url and not body.crafty_url.lower().startswith("https://"):
        raise HTTPException(status_code=400, detail="Crafty Controller URL must use HTTPS")
    if any(not node.strip() for node in body.proxmox_allowed_nodes):
        raise HTTPException(status_code=400, detail="Proxmox node names cannot be empty")
    if any(guest < 1 for guest in body.proxmox_allowed_guests):
        raise HTTPException(status_code=400, detail="Proxmox guest IDs must be positive")
    aliases = [target.alias for target in body.ssh_hosts]
    if len(aliases) != len(set(aliases)):
        raise HTTPException(status_code=400, detail="SSH host aliases must be unique")
    if settings.config_file is None:
        raise HTTPException(status_code=500, detail="Local config file is disabled")

    config = body.model_dump()
    config["ollama_wol_mac"] = wol_mac
    config["ollama_wol_broadcast"] = wol_broadcast
    ssh_hosts = config.pop("ssh_hosts")
    config["proxmox_allowed_nodes"] = sorted(
        set(node.strip() for node in body.proxmox_allowed_nodes)
    )
    config["proxmox_allowed_guests"] = sorted(set(body.proxmox_allowed_guests))
    config["proxmox_ca_file"] = body.proxmox_ca_file.strip() or None
    config["crafty_ca_file"] = body.crafty_ca_file.strip() or None
    config["crafty_allowed_servers"] = sorted(
        set(
            server_id.strip()
            for server_id in body.crafty_allowed_servers
            if server_id.strip()
        )
    )
    config["ssh_key_file"] = body.ssh_key_file.strip() or None
    config["ssh_hosts_json"] = json.dumps(
        {
            target["alias"]: {
                "hostname": target["hostname"].strip(),
                "services": sorted(set(target["services"])),
                "ports": sorted(set(target["ports"])),
                "ssh_port": target["ssh_port"],
            }
            for target in ssh_hosts
        },
        separators=(",", ":"),
    )
    path = settings.config_file.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    services.audit.record(
        "configuration_updated",
        input_data={
            **config,
            "proxmox_token_secret_configured": bool(settings.proxmox_token_secret),
        },
        output_data={"restart_required": True},
        success=True,
    )
    return {
        "saved": True,
        "restart_required": True,
        "config_file": str(path),
        "message": "Configuration saved. Restart the app to apply it.",
    }


@router.post("/restart")
def restart(
    request: Request,
    services: Services,
    _authorized: AuthorizedSetup,
) -> dict[str, Any]:
    shutdown_callback = request.app.state.shutdown_callback
    if shutdown_callback is None:
        raise HTTPException(
            status_code=409,
            detail="Restart is available only when launched with: python -m home_agent",
        )
    request.app.state.restart_requested = True
    services.audit.record("application_restart_requested", success=True)
    timer = threading.Timer(0.75, shutdown_callback)
    timer.daemon = True
    timer.start()
    return {"restarting": True, "message": "The application is restarting."}


@router.post("/setup/discover/crafty")
def discover_crafty_servers(
    services: Services,
    _authorized: AuthorizedSetup,
) -> dict[str, Any]:
    try:
        data = services.crafty.request("GET", "servers") or []
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if isinstance(data, dict):
        data = data.get("servers", [])
    if not isinstance(data, list):
        raise HTTPException(
            status_code=502,
            detail="Crafty returned an unexpected server-list shape",
        )
    servers = []
    for item in data:
        if not isinstance(item, dict):
            continue
        server_id = str(
            item.get("server_id")
            or item.get("server_uuid")
            or item.get("id")
            or ""
        )
        if server_id:
            servers.append(
                {
                    "id": server_id,
                    "name": item.get("server_name") or item.get("name") or server_id,
                }
            )
    return {"servers": servers}
