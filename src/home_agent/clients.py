from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class ExternalServiceError(RuntimeError):
    pass


class ProxmoxClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.proxmox_token_id and self.settings.proxmox_token_secret)

    def _verify(self) -> bool | str:
        if self.settings.proxmox_insecure_tls:
            return False
        if self.settings.proxmox_ca_file:
            return str(self.settings.proxmox_ca_file)
        return True

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.configured:
            raise ExternalServiceError("Proxmox credentials are not configured")
        headers = {
            "Authorization": (
                f"PVEAPIToken={self.settings.proxmox_token_id}="
                f"{self.settings.proxmox_token_secret}"
            )
        }
        url = f"{self.settings.proxmox_url.rstrip('/')}/api2/json/{path.lstrip('/')}"
        try:
            with httpx.Client(verify=self._verify(), timeout=self.settings.request_timeout_seconds) as client:
                response = client.request(method, url, headers=headers, **kwargs)
                response.raise_for_status()
                payload = response.json()
        except httpx.ConnectError as exc:
            raise ExternalServiceError(f"Cannot reach Proxmox at {self.settings.proxmox_url}") from exc
        except httpx.ConnectTimeout as exc:
            raise ExternalServiceError("Proxmox request timed out") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise ExternalServiceError("Proxmox rejected the API token or lacks permission") from exc
            raise ExternalServiceError(f"Proxmox returned HTTP {exc.response.status_code}") from exc
        except httpx.TransportError as exc:
            message = str(exc).lower()
            if "certificate" in message or "ssl" in message:
                raise ExternalServiceError(
                    "Proxmox TLS verification failed. Configure HOME_AGENT_PROXMOX_CA_FILE; "
                    "do not disable verification except as a temporary explicit choice."
                ) from exc
            raise ExternalServiceError(f"Proxmox connection failed: {exc}") from exc
        except (ValueError, KeyError) as exc:
            raise ExternalServiceError("Proxmox returned an invalid JSON response") from exc
        return payload.get("data")


class OllamaClient:
    def __init__(self, settings: Settings):
        self.settings = settings

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
            with httpx.Client(timeout=timeout_seconds or self.settings.request_timeout_seconds) as client:
                response = client.post(url, json=body)
                response.raise_for_status()
                payload = response.json()
        except httpx.ConnectError as exc:
            raise ExternalServiceError(
                f"Cannot reach Ollama at {self.settings.ollama_url}. Is 'ollama serve' running?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ExternalServiceError("Ollama response timed out") from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            raise ExternalServiceError(f"Ollama returned HTTP {exc.response.status_code}: {detail}") from exc
        except (ValueError, KeyError) as exc:
            raise ExternalServiceError("Ollama returned an invalid response") from exc
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ExternalServiceError("Ollama response did not contain a chat message")
        return message

    def health(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=3) as client:
                response = client.get(f"{self.settings.ollama_url.rstrip('/')}/api/tags")
                response.raise_for_status()
                models = [item.get("name") for item in response.json().get("models", [])]
            return {"ok": True, "models": models}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
