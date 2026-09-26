from __future__ import annotations

import ipaddress
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .container import AppServices


def get_services(request: Request) -> AppServices:
    return request.app.state.services


Services = Annotated[AppServices, Depends(get_services)]


def require_local_request(request: Request, services: Services) -> None:
    if services.settings.host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(
            status_code=403,
            detail="Web setup is disabled when the app is not bound exclusively to localhost",
        )
    client_host = request.client.host if request.client else ""
    try:
        is_loopback = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        is_loopback = client_host == "localhost"
    if not is_loopback:
        raise HTTPException(status_code=403, detail="Web setup is available only from localhost")


def require_setup_token(request: Request, services: Services) -> None:
    require_local_request(request, services)
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
