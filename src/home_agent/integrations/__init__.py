from .errors import ExternalServiceError
from .ollama import OllamaClient
from .proxmox import ProxmoxClient
from .wake_on_lan import build_magic_packet, send_magic_packet

__all__ = [
    "CraftyClient",
    "ExternalServiceError",
    "OllamaClient",
    "ProxmoxClient",
    "build_magic_packet",
    "send_magic_packet",
]
from .crafty import CraftyClient
