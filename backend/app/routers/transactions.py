from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import date

from app.db.database import get_db
from app.schemas.transaction_schema import (
    TransactionListResponse, FinancialEventOut, FinancialStateOut
)
from app.services.ingestion_service import IngestionService
from app.services.classification_service import (
    normalize_category, is_paycheck, extract_payroll_source, detect_recurring_income,
)
from app.models.transaction_model import Transaction, FinancialState
from app.models.plaid_model import Account, AccountBalance
from app.models.paycheck_model import Paycheck
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


@router.post("/reclassify")
async def reclassify_transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-run category normalization over all existing transactions for this user.
    - Fixes GUSTO/ADP/PAYCHEX mis-classified as RENT_AND_UTILITIES or other wrong categories.
    - Detects recurring credits > $500 that look like payroll even without keyword matches.
    - Upserts Paycheck records for all confirmed paycheck transactions.
    - Recalculates FinancialState so the dashboard reflects corrected figures.
    """
    # Fetch all transactions for this user
    txn_result = await db.execute(
        select(Transaction).where(Transaction.user_id == current_user.id)
    )
    all_txns = txn_result.scalars().all()

    reclassified = 0
    for txn in all_txns:
        corrected = normalize_category(
            txn.raw_name, txn.merchant_name, txn.category_primary, float(txn.amount)
        )
        if corrected != txn.category_primary:
            txn.category_primary = corrected
            reclassified += 1

    # Also detect recurring income that wasn't caught by keywords
    recurring = detect_recurring_income(all_txns)
    for txn in recurring:
        if txn.category_primary != "INCOME":
            txn.category_primary = "INCOME"
            reclassified += 1

    await db.flush()

    # Upsert Paycheck records for every confirmed paycheck transaction
    paychecks_created = 0
    for txn in all_txns:
        if not is_paycheck(float(txn.amount), txn.category_primary, txn.raw_name, txn.merchant_name):
            continue
        existing_pc = await db.execute(
            select(Paycheck).where(Paycheck.transaction_id == txn.id)
        )
        if existing_pc.scalar_one_or_none():
            continue
        db.add(Paycheck(
            user_id=current_user.id,
            transaction_id=txn.id,
            amount=abs(float(txn.amount)),
            source=extract_payroll_source(txn.raw_name, txn.merchant_name),
        ))
        paychecks_created += 1

    await db.flush()

    # Recalculate FinancialState from corrected data
    from datetime import datetime, timedelta, timezone

    acct_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    db_accounts_list = acct_result.scalars().all()
    db_accounts = {a.plaid_account_id: a for a in db_accounts_list}

    liquid = 0.0
    for acct in db_accounts_list:
        if "depository" not in acct.type:
            continue
        bal_result = await db.execute(
            select(AccountBalance.current)
            .where(AccountBalance.account_id == acct.id)
            .order_by(AccountBalance.snapshot_at.desc())
            .limit(1)
        )
        val = bal_result.scalar_one_or_none()
        if val is not None:
            liquid += float(val)

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
    recent_txns = [t for t in all_txns if not t.pending and t.posted_at >= cutoff]

    monthly_income = 0.0
    monthly_expenses = 0.0
    for txn in recent_txns:
        amt = float(txn.amount)
        is_income = (amt < 0) or (txn.category_primary == "INCOME")
        if is_income:
            monthly_income += abs(amt)
        elif amt > 0:
            monthly_expenses += amt

    emergency_score = (liquid / monthly_expenses) if monthly_expenses > 0 else None

    state_result = await db.execute(
        select(FinancialState).where(FinancialState.user_id == current_user.id)
    )
    state = state_result.scalar_one_or_none()
    if state:
        state.total_liquid_balance = liquid
        state.monthly_income_est = monthly_income or None
        state.monthly_expenses_est = monthly_expenses or None
        state.emergency_fund_score = emergency_score
    else:
        db.add(FinancialState(
            user_id=current_user.id,
            total_liquid_balance=liquid,
            monthly_income_est=monthly_income or None,
            monthly_expenses_est=monthly_expenses or None,
            emergency_fund_score=emergency_score,
        ))

    return {
        "reclassified": reclassified,
        "paychecks_created": paychecks_created,
        "monthly_income_est": monthly_income,
        "monthly_expenses_est": monthly_expenses,
        "total_liquid_balance": liquid,
    }


@router.get("/events", response_model=list[FinancialEventOut])
async def list_events(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = IngestionService(db)
    return await svc.list_events(current_user.id, limit=limit)
