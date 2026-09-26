from typing import Any

from fastapi import APIRouter

from ..dependencies import Services, voice_available

router = APIRouter()


@router.get("/api/config")
def public_config(services: Services) -> dict[str, Any]:
    settings = services.settings
    return {
        "model": settings.ollama_model,
        "proxmox_configured": services.proxmox.configured,
        "insecure_tls": settings.proxmox_insecure_tls,
        "voice_available": voice_available(),
        "allowed_nodes": list(settings.proxmox_allowed_nodes),
        "allowed_guests": list(settings.proxmox_allowed_guests),
        "ssh_hosts": list(settings.ssh_hosts),
    }


@router.get("/health")
def health(services: Services) -> dict[str, Any]:
    ollama_status = services.ollama.health()
    return {
        "status": "ok" if ollama_status["ok"] else "degraded",
        "ollama": ollama_status,
        "proxmox_configured": services.proxmox.configured,
        "insecure_tls": services.settings.proxmox_insecure_tls,
    }
