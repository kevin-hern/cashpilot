from fastapi import APIRouter, Depends, Request, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.plaid_schema import (
    LinkTokenResponse, ExchangeRequest, ExchangeResponse,
    PlaidItemOut, AccountOut, PlaidWebhookPayload,
)
from app.services.plaid_service import PlaidService
from app.services.audit_service import AuditService
from app.dependencies import get_current_user
from app.models.user_model import User
import uuid

router = APIRouter()


@router.post("/link-token", response_model=LinkTokenResponse)
async def create_link_token(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = PlaidService(db)
    return await svc.create_link_token(current_user)


@router.post("/exchange", response_model=ExchangeResponse, status_code=status.HTTP_201_CREATED)
async def exchange_public_token(
    body: ExchangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = PlaidService(db)
    return await svc.exchange_public_token(current_user, body)


@router.get("/items", response_model=list[PlaidItemOut])
async def list_items(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = PlaidService(db)
    return await svc.list_items(current_user.id)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_item(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = PlaidService(db)
    await svc.unlink_item(current_user.id, item_id)


@router.post("/sync/{item_id}", status_code=status.HTTP_200_OK)
async def manual_sync(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = PlaidService(db)
    await svc.trigger_sync(current_user.id, item_id)
    await db.commit()
    return {"message": "Sync complete"}


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def plaid_webhook(
    request: Request,
    plaid_verification: str | None = Header(None, alias="Plaid-Verification"),
    db: AsyncSession = Depends(get_db),
):
    """Receive and verify Plaid webhooks. Responds immediately; processing is async."""
    body_bytes = await request.body()
    svc = PlaidService(db)

    if not await svc.verify_webhook_signature(body_bytes, plaid_verification):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    payload = PlaidWebhookPayload.model_validate(await request.json())
    await svc.enqueue_webhook(payload)
    return {"received": True}
