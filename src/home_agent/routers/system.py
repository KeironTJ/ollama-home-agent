from typing import Any

from fastapi import APIRouter

from ..dependencies import Services, voice_available

router = APIRouter()


@router.get("/api/config")
def public_config(services: Services) -> dict[str, Any]:
    settings = services.settings
    insecure_tls = (
        settings.proxmox_insecure_tls or settings.crafty_insecure_tls
    )
    return {
        "model": settings.ollama_model,
        "proxmox_configured": services.proxmox.configured,
        "crafty_configured": services.crafty.configured,
        "insecure_tls": insecure_tls,
        "proxmox_insecure_tls": settings.proxmox_insecure_tls,
        "crafty_insecure_tls": settings.crafty_insecure_tls,
        "voice_available": voice_available(),
        "allowed_nodes": list(settings.proxmox_allowed_nodes),
        "allowed_guests": list(settings.proxmox_allowed_guests),
        "ssh_hosts": list(settings.ssh_hosts),
    }


@router.get("/health")
def health(services: Services) -> dict[str, Any]:
    ollama_status = services.ollama.health()
    crafty_status = services.crafty.health()
    healthy = ollama_status["ok"] and (
        not services.crafty.configured or crafty_status["ok"]
    )
    return {
        "status": "ok" if healthy else "degraded",
        "ollama": ollama_status,
        "crafty": crafty_status,
        "proxmox_configured": services.proxmox.configured,
        "insecure_tls": (
            services.settings.proxmox_insecure_tls
            or services.settings.crafty_insecure_tls
        ),
        "proxmox_insecure_tls": services.settings.proxmox_insecure_tls,
        "crafty_insecure_tls": services.settings.crafty_insecure_tls,
    }
