from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.db.database import get_db
from app.schemas.intent_schema import IntentOut, ApproveRequest, RejectRequest, ExecutionOut
from app.services.approval_service import ApprovalService
from app.dependencies import get_current_user
from app.models.user_model import User

router = APIRouter()


@router.get("/", response_model=list[IntentOut])
async def list_pending(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ApprovalService(db)
    return await svc.list_pending(current_user.id)


@router.get("/{intent_id}", response_model=IntentOut)
async def get_intent(
    intent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ApprovalService(db)
    intent = await svc.get_intent(current_user.id, intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    return intent


@router.post("/{intent_id}/approve", response_model=ExecutionOut, status_code=status.HTTP_202_ACCEPTED)
async def approve_intent(
    intent_id: uuid.UUID,
    body: ApproveRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve an intent and trigger execution.
    Requires a client-generated idempotency_key to prevent double-execution.
    """
    svc = ApprovalService(db)
    return await svc.approve(
        user=current_user,
        intent_id=intent_id,
        idempotency_key=body.idempotency_key,
        request=request,
    )


@router.post("/{intent_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_intent(
    intent_id: uuid.UUID,
    body: RejectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ApprovalService(db)
    await svc.reject(current_user.id, intent_id, reason=body.reason)
