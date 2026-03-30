from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import uuid

from app.db.database import get_db
from app.dependencies import get_current_user
from app.models.user_model import User
from app.models.plaid_model import Account, AccountBalance

router = APIRouter()


class AccountWithBalance(BaseModel):
    id: uuid.UUID
    name: str
    official_name: str | None
    type: str
    subtype: str | None
    currency: str
    is_primary: bool
    current_balance: float | None
    available_balance: float | None
    plaid_item_id: uuid.UUID

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[AccountWithBalance])
async def list_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all accounts for the current user with their latest balance snapshot."""
    result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    accounts = result.scalars().all()

    out = []
    for acct in accounts:
        # Fetch most recent balance snapshot
        bal_result = await db.execute(
            select(AccountBalance)
            .where(AccountBalance.account_id == acct.id)
            .order_by(AccountBalance.snapshot_at.desc())
            .limit(1)
        )
        bal = bal_result.scalar_one_or_none()

        out.append(AccountWithBalance(
            id=acct.id,
            name=acct.name,
            official_name=acct.official_name,
            type=acct.type,
            subtype=acct.subtype,
            currency=acct.currency,
            is_primary=acct.is_primary,
            plaid_item_id=acct.plaid_item_id,
            current_balance=float(bal.current) if bal else None,
            available_balance=float(bal.available) if bal and bal.available is not None else None,
        ))
    return out
