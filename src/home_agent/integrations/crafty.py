from __future__ import annotations

from typing import Any

import httpx

from ..core.config import Settings
from ..core.tls import verified_ssl_context
from .errors import ExternalServiceError


class CraftyClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.crafty_url
            and self.settings.crafty_read_token
            and self.settings.crafty_allowed_servers
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        action: bool = False,
        authenticated: bool = True,
        **kwargs: Any,
    ) -> Any:
        if not self.settings.crafty_url:
            raise ExternalServiceError("Crafty Controller URL is not configured")
        headers = {}
        if authenticated:
            token = (
                self.settings.crafty_action_token
                if action
                else self.settings.crafty_read_token
            )
            if not token:
                kind = "action" if action else "read"
                raise ExternalServiceError(
                    f"Crafty Controller {kind} API token is not configured"
                )
            headers["Authorization"] = f"Bearer {token}"
        url = (
            f"{self.settings.crafty_url.rstrip('/')}/api/v2/"
            f"{path.lstrip('/')}"
        )
        try:
            with httpx.Client(
                verify=verified_ssl_context(
                    self.settings.crafty_ca_file,
                    self.settings.crafty_insecure_tls,
                ),
                timeout=self.settings.request_timeout_seconds,
            ) as client:
                response = client.request(
                    method,
                    url,
                    headers=headers,
                    **kwargs,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.ConnectError as exc:
            message = str(exc).lower()
            if "certificate" in message or "ssl" in message:
                raise ExternalServiceError(
                    "Crafty TLS verification failed. Configure its CA certificate "
                    "or install a trusted certificate."
                ) from exc
            raise ExternalServiceError(
                f"Cannot reach Crafty Controller at {self.settings.crafty_url}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ExternalServiceError("Crafty Controller request timed out") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise ExternalServiceError(
                    "Crafty Controller rejected the API token or lacks permission"
                ) from exc
            raise ExternalServiceError(
                f"Crafty Controller returned HTTP {exc.response.status_code}"
            ) from exc
        except (ValueError, KeyError) as exc:
            raise ExternalServiceError(
                "Crafty Controller returned an invalid JSON response"
            ) from exc
        if isinstance(payload, dict) and payload.get("status") == "error":
            raise ExternalServiceError(
                f"Crafty Controller error: {payload.get('error', 'unknown error')}"
            )
        return payload.get("data") if isinstance(payload, dict) else payload

    def health(self) -> dict[str, Any]:
        if not self.settings.crafty_url:
            return {"ok": False, "configured": False}
        try:
            self.request("GET", "crafty/check", authenticated=False)
            return {"ok": True, "configured": True}
        except ExternalServiceError as exc:
            return {
                "ok": False,
                "configured": self.configured,
                "error": str(exc),
            }
