from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .core.config import Settings
from .container import build_services
from .routers import approvals, chat, history, pages, setup, system, voice

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    services = build_services(settings)

    app = FastAPI(title="Home Diagnostic Agent", version="0.1.0")
    app.state.services = services
    app.state.setup_token = secrets.token_urlsafe(32)
    app.state.restart_requested = False
    app.state.shutdown_callback = None

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pages.router)
    app.include_router(system.router)
    app.include_router(chat.router)
    app.include_router(history.router)
    app.include_router(approvals.router)
    app.include_router(setup.router)
    app.include_router(voice.router)
    return app


app = create_app()
