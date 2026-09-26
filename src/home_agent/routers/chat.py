import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from ..integrations import ExternalServiceError
from ..dependencies import Services
from ..schemas import ChatRequest

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
def chat(body: ChatRequest, services: Services) -> dict[str, Any]:
    session_id = body.session_id or str(uuid.uuid4())
    services.history.add_message(session_id, "user", body.message)
    try:
        result = services.coordinator.run(body.message, session_id)
        services.history.add_message(
            session_id,
            "assistant",
            result["message"],
            result.get("artifacts", []),
        )
        return {"session_id": session_id, **result}
    except (ValueError, ExternalServiceError) as exc:
        services.history.add_message(session_id, "assistant", f"Error: {exc}")
        services.audit.record(
            "assistant_error",
            session_id=session_id,
            output_data=str(exc),
            success=False,
        )
        status = 503 if isinstance(exc, ExternalServiceError) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
