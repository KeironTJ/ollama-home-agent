from __future__ import annotations

import socket

from ..core.config import normalize_mac_address


def build_magic_packet(mac_address: str) -> bytes:
    normalized = normalize_mac_address(mac_address)
    if not normalized:
        raise ValueError("Wake-on-LAN MAC address is not configured")
    mac_bytes = bytes.fromhex(normalized.replace(":", ""))
    return b"\xff" * 6 + mac_bytes * 16


def send_magic_packet(
    mac_address: str,
    broadcast_address: str,
    port: int,
) -> None:
    packet = build_magic_packet(mac_address)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        client.sendto(packet, (broadcast_address, port))
