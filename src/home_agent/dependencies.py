from __future__ import annotations

import ipaddress
import secrets
import threading
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .container import AppServices


def get_services(request: Request) -> AppServices:
    return request.app.state.services


Services = Annotated[AppServices, Depends(get_services)]


MIN_ADMIN_PASSWORD_LENGTH = 12
ADMIN_FAILURE_LIMIT = 10
ADMIN_LOCKOUT_SECONDS = 300
ADMIN_PASSWORD_HEADER = "x-home-agent-admin-password"

_admin_failures: dict[str, list[float]] = {}
_admin_failures_lock = threading.Lock()


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


def _is_local_only(request: Request, services: Services) -> bool:
    if services.settings.host not in {"127.0.0.1", "::1", "localhost"}:
        return False
    client_host = _client_host(request)
    try:
        return ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        return client_host == "localhost"


def _recent_failures(client: str, now: float) -> list[float]:
    failures = [
        moment
        for moment in _admin_failures.get(client, [])
        if now - moment < ADMIN_LOCKOUT_SECONDS
    ]
    if failures:
        _admin_failures[client] = failures
    else:
        _admin_failures.pop(client, None)
    return failures


def require_admin_request(request: Request, services: Services) -> None:
    """Allow setup from localhost, or from the network with the admin password."""
    if _is_local_only(request, services):
        return
    expected = services.settings.admin_password
    if not expected:
        raise HTTPException(
            status_code=403,
            detail=(
                "Remote setup is disabled. Set HOME_AGENT_ADMIN_PASSWORD in the "
                "server environment file and restart, or use setup from localhost."
            ),
        )
    if len(expected) < MIN_ADMIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=403,
            detail=(
                "Remote setup is disabled: HOME_AGENT_ADMIN_PASSWORD must be at "
                f"least {MIN_ADMIN_PASSWORD_LENGTH} characters."
            ),
        )
    client = _client_host(request)
    now = time.monotonic()
    with _admin_failures_lock:
        if len(_recent_failures(client, now)) >= ADMIN_FAILURE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Too many failed admin password attempts; try again in a few minutes.",
            )
    supplied = request.headers.get(ADMIN_PASSWORD_HEADER, "")
    if not supplied:
        raise HTTPException(status_code=401, detail="Admin password required")
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        with _admin_failures_lock:
            _admin_failures.setdefault(client, []).append(now)
        services.audit.record(
            "admin_auth_failed",
            input_data={"client": client},
            success=False,
        )
        raise HTTPException(status_code=401, detail="Incorrect admin password")
    with _admin_failures_lock:
        _admin_failures.pop(client, None)


def require_local_request(request: Request, services: Services) -> None:
    require_admin_request(request, services)


def require_setup_token(request: Request, services: Services) -> None:
    require_admin_request(request, services)
    supplied_token = request.headers.get("x-home-agent-setup-token")
    expected_token = request.app.state.setup_token
    if not secrets.compare_digest(supplied_token or "", expected_token):
        raise HTTPException(status_code=403, detail="Invalid setup token; reload the setup page")


def voice_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True
