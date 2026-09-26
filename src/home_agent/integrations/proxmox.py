from __future__ import annotations

import ssl
from typing import Any

import httpx

from ..core.config import Settings
from .errors import ExternalServiceError


class ProxmoxClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.proxmox_token_id
            and "!" in self.settings.proxmox_token_id
            and self.settings.proxmox_token_secret
        )

    def _verify(self) -> bool | ssl.SSLContext:
        if self.settings.proxmox_insecure_tls:
            return False
        if self.settings.proxmox_ca_file:
            context = ssl.create_default_context(cafile=str(self.settings.proxmox_ca_file))
            strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
            if strict:
                context.verify_flags &= ~strict
            return context
        return True

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if self.settings.proxmox_token_id and "!" not in self.settings.proxmox_token_id:
            raise ExternalServiceError(
                "Proxmox token ID is incomplete. Use the full API token identity "
                "'user@realm!token-name', not only the user identity."
            )
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
            with httpx.Client(
                verify=self._verify(),
                timeout=self.settings.request_timeout_seconds,
            ) as client:
                response = client.request(method, url, headers=headers, **kwargs)
                response.raise_for_status()
                payload = response.json()
        except httpx.ConnectError as exc:
            message = str(exc).lower()
            if "certificate" in message or "ssl" in message:
                raise ExternalServiceError(
                    "Proxmox TLS verification failed. Check the configured CA certificate "
                    "and that the URL matches the certificate."
                ) from exc
            raise ExternalServiceError(
                f"Cannot reach Proxmox at {self.settings.proxmox_url}"
            ) from exc
        except httpx.ConnectTimeout as exc:
            raise ExternalServiceError("Proxmox request timed out") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise ExternalServiceError(
                    "Proxmox rejected the API token or lacks permission"
                ) from exc
            raise ExternalServiceError(
                f"Proxmox returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.TransportError as exc:
            raise ExternalServiceError(f"Proxmox connection failed: {exc}") from exc
        except (ValueError, KeyError) as exc:
            raise ExternalServiceError(
                "Proxmox returned an invalid JSON response"
            ) from exc
        return payload.get("data")
