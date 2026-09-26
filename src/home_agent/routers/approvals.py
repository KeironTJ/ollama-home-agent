from typing import Any

from fastapi import APIRouter, HTTPException

from ..dependencies import Services
from ..integrations import ExternalServiceError
from ..schemas import ApprovalDecision
from ..services.approvals import ApprovalError
from ..tools import ToolError

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.post("/{approval_id}")
def decide_approval(
    approval_id: str,
    body: ApprovalDecision,
    services: Services,
) -> dict[str, Any]:
    try:
        return services.approvals.decide(
            approval_id,
            body.approved,
            services.tools.execute_approved,
        )
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ToolError, ExternalServiceError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
