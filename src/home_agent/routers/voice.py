import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ..dependencies import Services, voice_available

router = APIRouter(prefix="/api", tags=["voice"])


@router.post("/transcribe")
async def transcribe(request: Request, services: Services) -> dict[str, str]:
    if not voice_available():
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
            model = WhisperModel(
                services.settings.whisper_model_size,
                device="cpu",
                compute_type="int8",
            )
            segments, _ = model.transcribe(str(temp_path), beam_size=1)
            text = " ".join(segment.text.strip() for segment in segments).strip()
        finally:
            temp_path.unlink(missing_ok=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Local transcription failed: {exc}") from exc
    services.audit.record("voice_transcription", output_data=text, success=True)
    return {"text": text}
