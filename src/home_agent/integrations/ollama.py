from __future__ import annotations

from typing import Any

import httpx

from ..core.config import Settings
from .errors import ExternalServiceError


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

    def health(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=3) as client:
                response = client.get(
                    f"{self.settings.ollama_url.rstrip('/')}/api/tags"
                )
                response.raise_for_status()
                models = [
                    item.get("name")
                    for item in response.json().get("models", [])
                ]
            return {"ok": True, "models": models}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
