from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.db.database import get_db
from app.schemas.intent_schema import IntentOut, ApproveRequest, RejectRequest, ExecutionOut, ChatIntentRequest
from app.models.intent_model import Intent
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.dependencies import get_current_user
from app.models.user_model import User

router = APIRouter()


@router.post("/", response_model=ExecutionOut, status_code=status.HTTP_201_CREATED)
async def create_and_approve_chat_intent(
    body: ChatIntentRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create an Intent from a chat-surfaced recommendation and immediately approve it.
    Writes intent.created + approval.actioned + execution.settled to audit_log.
    The idempotency_key prevents double-execution if the user clicks Approve twice.
    """
    audit = AuditService(db)

    intent = Intent(
        user_id=current_user.id,
        intent_type=body.intent_type,
        title=body.title,
        explanation=body.explanation,
        amount=body.amount,
        confidence_score=body.confidence,
        generated_by="llm",
        status="pending_approval",
    )
    db.add(intent)
    await db.flush()

    # Audit: intent created from chat
    await audit.log(
        event_type="intent.created",
        user_id=current_user.id,
        actor_type="user",
        actor_id=str(current_user.id),
        entity_type="intent",
        entity_id=intent.id,
        after_state={
            "source": "chat",
            "intent_type": body.intent_type,
            "title": body.title,
            "amount": body.amount,
            "confidence": body.confidence,
        },
        ip=request.client.host if request.client else None,
    )

    svc = ApprovalService(db)
    execution = await svc.approve(
        user=current_user,
        intent_id=intent.id,
        idempotency_key=body.idempotency_key,
        request=request,
    )
    await db.commit()
    return execution


@router.get("", response_model=list[IntentOut])
async def list_intents(
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Comma-separated statuses. Omit for all. E.g. pending_approval,approved,executed",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List intents for the current user. Defaults to all statuses."""
    svc = ApprovalService(db)
    statuses = [s.strip() for s in status_filter.split(",")] if status_filter else None
    return await svc.list_intents(current_user.id, statuses=statuses)


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
    Approve a pre-existing intent and trigger execution.
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
