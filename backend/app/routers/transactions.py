from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import date
from sqlalchemy import func, extract
from pydantic import BaseModel
from typing import Any

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


class TransactionSummary(BaseModel):
    id: str
    raw_name: str | None
    merchant_name: str | None
    amount: float
    posted_at: str

class CategoryBreakdown(BaseModel):
    category: str
    total: float
    count: int
    percentage: float
    prev_month_total: float | None
    top_transactions: list[TransactionSummary]

class SpendingBreakdownResponse(BaseModel):
    month: int
    year: int
    total_spending: float
    categories: list[CategoryBreakdown]


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


@router.get("/categories", response_model=SpendingBreakdownResponse)
async def get_spending_by_category(
    month: int = Query(None, ge=1, le=12),
    year: int = Query(None, ge=2020, le=2100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, date as date_type
    import calendar

    now = datetime.utcnow()
    if month is None:
        month = now.month
    if year is None:
        year = now.year

    # Date range for selected month
    first_day = date_type(year, month, 1)
    last_day = date_type(year, month, calendar.monthrange(year, month)[1])

    # Previous month
    if month == 1:
        prev_month, prev_year = 12, year - 1
    else:
        prev_month, prev_year = month - 1, year
    prev_first = date_type(prev_year, prev_month, 1)
    prev_last = date_type(prev_year, prev_month, calendar.monthrange(prev_year, prev_month)[1])

    # Fetch expense transactions for selected month (amount > 0, not INCOME, not pending)
    txn_result = await db.execute(
        select(Transaction).where(
            Transaction.user_id == current_user.id,
            Transaction.pending == False,
            Transaction.amount > 0,
            Transaction.category_primary != "INCOME",
            Transaction.posted_at >= first_day,
            Transaction.posted_at <= last_day,
        )
    )
    txns = txn_result.scalars().all()

    # Fetch previous month expenses for comparison
    prev_result = await db.execute(
        select(Transaction).where(
            Transaction.user_id == current_user.id,
            Transaction.pending == False,
            Transaction.amount > 0,
            Transaction.category_primary != "INCOME",
            Transaction.posted_at >= prev_first,
            Transaction.posted_at <= prev_last,
        )
    )
    prev_txns = prev_result.scalars().all()

    # Group by category
    from collections import defaultdict
    cat_txns: dict[str, list] = defaultdict(list)
    for t in txns:
        cat = t.category_primary or "OTHER"
        cat_txns[cat].append(t)

    prev_cat_totals: dict[str, float] = defaultdict(float)
    for t in prev_txns:
        cat = t.category_primary or "OTHER"
        prev_cat_totals[cat] += float(t.amount)

    total_spending = sum(float(t.amount) for t in txns)

    categories: list[CategoryBreakdown] = []
    for cat, cat_list in sorted(cat_txns.items(), key=lambda x: -sum(float(t.amount) for t in x[1])):
        cat_total = sum(float(t.amount) for t in cat_list)
        top5 = sorted(cat_list, key=lambda t: -float(t.amount))[:5]
        categories.append(CategoryBreakdown(
            category=cat,
            total=round(cat_total, 2),
            count=len(cat_list),
            percentage=round((cat_total / total_spending * 100) if total_spending > 0 else 0, 1),
            prev_month_total=round(prev_cat_totals[cat], 2) if cat in prev_cat_totals else None,
            top_transactions=[
                TransactionSummary(
                    id=str(t.id),
                    raw_name=t.raw_name,
                    merchant_name=t.merchant_name,
                    amount=round(float(t.amount), 2),
                    posted_at=str(t.posted_at),
                )
                for t in top5
            ],
        ))

    return SpendingBreakdownResponse(
        month=month,
        year=year,
        total_spending=round(total_spending, 2),
        categories=categories,
    )


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
