from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .agent import AgentRunner
from .approvals import ApprovalError, ApprovalStore
from .audit import AuditLog
from .clients import ExternalServiceError, OllamaClient, ProxmoxClient
from .config import Settings
from .tools import DiagnosticTools, ToolError

STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)
    session_id: str | None = Field(default=None, max_length=100)


class ApprovalDecision(BaseModel):
    approved: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(settings.database_path, settings.audit_max_output_chars)
    approvals = ApprovalStore(audit, settings.approval_ttl_seconds)
    proxmox = ProxmoxClient(settings)
    ollama = OllamaClient(settings)
    tools = DiagnosticTools(settings, proxmox, approvals, audit)
    runner = AgentRunner(settings, ollama, tools, audit)

    app = FastAPI(title="Home Diagnostic Agent", version="0.1.0")
    app.state.settings = settings
    app.state.audit = audit
    app.state.approvals = approvals
    app.state.tools = tools
    app.state.runner = runner
    app.state.ollama = ollama

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    def public_config() -> dict[str, Any]:
        return {
            "model": settings.ollama_model,
            "proxmox_configured": proxmox.configured,
            "insecure_tls": settings.proxmox_insecure_tls,
            "voice_available": _voice_available(),
            "allowed_nodes": list(settings.proxmox_allowed_nodes),
            "allowed_guests": list(settings.proxmox_allowed_guests),
            "ssh_hosts": list(settings.ssh_hosts),
        }

    @app.get("/health")
    def health() -> dict[str, Any]:
        ollama_status = ollama.health()
        return {
            "status": "ok" if ollama_status["ok"] else "degraded",
            "ollama": ollama_status,
            "proxmox_configured": proxmox.configured,
            "insecure_tls": settings.proxmox_insecure_tls,
        }

    @app.post("/api/chat")
    def chat(body: ChatRequest) -> dict[str, Any]:
        session_id = body.session_id or str(uuid.uuid4())
        try:
            result = runner.run(body.message, session_id)
            return {"session_id": session_id, **result}
        except (ValueError, ExternalServiceError) as exc:
            audit.record("assistant_error", session_id=session_id, output_data=str(exc), success=False)
            raise HTTPException(status_code=503 if isinstance(exc, ExternalServiceError) else 400, detail=str(exc)) from exc

    @app.post("/api/approvals/{approval_id}")
    def decide_approval(approval_id: str, body: ApprovalDecision) -> dict[str, Any]:
        try:
            return approvals.decide(approval_id, body.approved, tools.execute_approved)
        except ApprovalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ToolError, ExternalServiceError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/transcribe")
    async def transcribe(request: Request) -> dict[str, str]:
        if not _voice_available():
            raise HTTPException(
                status_code=501,
                detail='Local voice support is not installed. Run: pip install -e ".[voice]"',
            )
        audio = await request.body()
        if not audio:
            raise HTTPException(status_code=400, detail="Audio body is empty")
        if len(audio) > 15 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Audio exceeds the 15 MB local limit")
        suffix = request.headers.get("x-audio-extension", ".webm")
        if suffix not in (".webm", ".wav", ".mp3", ".m4a", ".ogg"):
            suffix = ".webm"
        try:
            from faster_whisper import WhisperModel

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(audio)
                temp_path = Path(handle.name)
            try:
                model = WhisperModel(settings.whisper_model_size, device="cpu", compute_type="int8")
                segments, _ = model.transcribe(str(temp_path), beam_size=1)
                text = " ".join(segment.text.strip() for segment in segments).strip()
            finally:
                temp_path.unlink(missing_ok=True)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Local transcription failed: {exc}") from exc
        audit.record("voice_transcription", output_data=text, success=True)
        return {"text": text}

    return app


def _voice_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


app = create_app()

