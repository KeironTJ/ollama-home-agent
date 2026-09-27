from __future__ import annotations

import time
from typing import Any

import httpx

from ..core.config import Settings
from .errors import ExternalServiceError
from .wake_on_lan import send_magic_packet


class OllamaClient:
    def __init__(self, settings: Settings, wake_sender=send_magic_packet):
        self.settings = settings
        self._wake_sender = wake_sender

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        url = f"{self.settings.ollama_url.rstrip('/')}/api/chat"
        body = {
            "model": self.settings.ollama_model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 900},
        }
        try:
            timeout = timeout_seconds or self.settings.request_timeout_seconds
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, json=body)
                response.raise_for_status()
                payload = response.json()
        except httpx.ConnectError as exc:
            raise ExternalServiceError(
                f"Cannot reach Ollama at {self.settings.ollama_url}. "
                "Is 'ollama serve' running?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ExternalServiceError("Ollama response timed out") from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            raise ExternalServiceError(
                f"Ollama returned HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except (ValueError, KeyError) as exc:
            raise ExternalServiceError(
                "Ollama returned an invalid response"
            ) from exc
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ExternalServiceError(
                "Ollama response did not contain a chat message"
            )
        return message

    def health(self, timeout_seconds: float = 3) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(
                    f"{self.settings.ollama_url.rstrip('/')}/api/tags"
                )
                response.raise_for_status()
                models = [
                    item.get("name")
                    for item in response.json().get("models", [])
                ]
            return {
                "ok": True,
                "state": "ready",
                "models": models,
                "device": self.settings.ollama_device_name,
                "wake_enabled": self.settings.ollama_wol_configured,
            }
        except Exception as exc:
            return {
                "ok": False,
                "state": (
                    "standby"
                    if self.settings.ollama_wol_configured
                    else "unavailable"
                ),
                "error": str(exc),
                "device": self.settings.ollama_device_name,
                "wake_enabled": self.settings.ollama_wol_configured,
            }

    def ensure_ready(self) -> dict[str, Any]:
        status = self.health()
        if status["ok"]:
            return {"ready": True, "wake_sent": False, "attempts": 0}
        if not self.settings.ollama_wol_enabled:
            raise ExternalServiceError(
                f"Cannot reach Ollama at {self.settings.ollama_url}. "
                f"Compute device '{self.settings.ollama_device_name}' is offline "
                "and Wake-on-LAN is disabled."
            )
        if not self.settings.ollama_wol_mac:
            raise ExternalServiceError(
                "Wake-on-LAN is enabled but no valid MAC address is configured"
            )

        try:
            self._wake_sender(
                self.settings.ollama_wol_mac,
                self.settings.ollama_wol_broadcast,
                self.settings.ollama_wol_port,
            )
        except OSError as exc:
            raise ExternalServiceError(
                f"Could not send Wake-on-LAN packet for "
                f"'{self.settings.ollama_device_name}': {exc}"
            ) from exc

        deadline = time.monotonic() + self.settings.ollama_wake_timeout_seconds
        attempts = 0
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            time.sleep(min(self.settings.ollama_wake_poll_seconds, remaining))
            attempts += 1
            remaining = max(0.1, deadline - time.monotonic())
            status = self.health(timeout_seconds=min(2, remaining))
            if status["ok"]:
                return {
                    "ready": True,
                    "wake_sent": True,
                    "attempts": attempts,
                }

        raise ExternalServiceError(
            f"Woke '{self.settings.ollama_device_name}', but Ollama did not "
            f"become ready within {self.settings.ollama_wake_timeout_seconds:g} seconds"
        )
