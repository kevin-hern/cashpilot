from fastapi import APIRouter, Depends, Request, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import traceback

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

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/link-token", response_model=LinkTokenResponse)
async def create_link_token(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        svc = PlaidService(db)
        return await svc.create_link_token(current_user)
    except Exception as exc:
        logger.error("link-token failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"link-token error: {exc}")


@router.post("/exchange", response_model=ExchangeResponse, status_code=status.HTTP_201_CREATED)
async def exchange_public_token(
    body: ExchangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info("exchange: start user=%s institution=%s", current_user.id, body.institution_name)
    try:
        svc = PlaidService(db)
        logger.info("exchange: calling Plaid item_public_token_exchange")
        result = await svc.exchange_public_token(current_user, body)
        logger.info("exchange: success item_id=%s", result.item_id)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("exchange: FAILED user=%s error=%s\n%s", current_user.id, exc, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Exchange failed: {exc}")


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
