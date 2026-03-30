from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date

from app.db.database import get_db
from app.schemas.transaction_schema import (
    TransactionListResponse, FinancialEventOut, FinancialStateOut
)
from app.services.ingestion_service import IngestionService
from app.dependencies import get_current_user
from app.models.user_model import User

router = APIRouter()


@router.get("/", response_model=TransactionListResponse)
async def list_transactions(
    account_id: str | None = Query(None),
    category: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = IngestionService(db)
    return await svc.list_transactions(
        current_user.id, account_id=account_id,
        category=category, start_date=start_date, end_date=end_date,
        page=page, limit=limit,
    )


@router.get("/state", response_model=FinancialStateOut)
async def get_financial_state(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = IngestionService(db)
    return await svc.get_financial_state(current_user.id)


@router.get("/events", response_model=list[FinancialEventOut])
async def list_events(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = IngestionService(db)
    return await svc.list_events(current_user.id, limit=limit)
