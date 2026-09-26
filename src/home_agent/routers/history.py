from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..dependencies import Services

router = APIRouter(prefix="/api/conversations", tags=["history"])


@router.get("")
def list_conversations(
    services: Services,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, Any]]:
    return services.history.list_conversations(limit)


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, services: Services) -> dict[str, Any]:
    messages = services.history.get_messages(conversation_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Conversation was not found")
    return {"id": conversation_id, "messages": messages}


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, services: Services) -> None:
    if not services.history.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation was not found")
