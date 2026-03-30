"""
Reclassify existing transactions and recalculate financial state for all users.

Run from backend/:
    source venv/bin/activate
    python -m scripts.reclassify_transactions
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# Ensure app package is importable
sys.path.insert(0, "/Users/kevin.hern/cashpilot/backend")

from sqlalchemy import select
from app.db.database import AsyncSessionLocal
import app.models  # noqa: F401 — registers all models with Base

from app.models.user_model import User
from app.models.plaid_model import Account, AccountBalance
from app.models.transaction_model import Transaction, FinancialState
from app.models.paycheck_model import Paycheck
from app.services.classification_service import (
    normalize_category, is_paycheck, extract_payroll_source,
    detect_recurring_income, detect_pay_frequency,
)


async def reclassify_user(session, user: User) -> dict:
    # ── 1. Fetch all transactions ─────────────────────────────────────────────
    txn_result = await session.execute(
        select(Transaction).where(Transaction.user_id == user.id)
    )
    all_txns = txn_result.scalars().all()

    if not all_txns:
        return {
            "user": str(getattr(user, "email", user.id)),
            "transactions": 0, "reclassified": 0, "paychecks_created": 0,
            "monthly_income": 0.0, "monthly_expenses": 0.0, "liquid_balance": 0.0,
            "pay_frequency": None,
        }

    # ── 2. Re-apply category normalization ────────────────────────────────────
    reclassified = 0
    for txn in all_txns:
        corrected = normalize_category(
            txn.raw_name, txn.merchant_name, txn.category_primary, float(txn.amount)
        )
        if corrected != txn.category_primary:
            print(f"  RECLASSIFY: '{txn.raw_name}' | {txn.category_primary} → {corrected} | ${txn.amount}")
            txn.category_primary = corrected
            reclassified += 1

    # ── 3. Detect recurring income mis-classified by Plaid ────────────────────
    recurring = detect_recurring_income(all_txns)
    for txn in recurring:
        if txn.category_primary != "INCOME":
            print(f"  RECURRING INCOME: '{txn.raw_name}' | {txn.category_primary} → INCOME | ${txn.amount}")
            txn.category_primary = "INCOME"
            reclassified += 1

    await session.flush()

    # ── 4. Upsert Paycheck records ────────────────────────────────────────────
    paychecks_created = 0
    for txn in all_txns:
        if not is_paycheck(float(txn.amount), txn.category_primary, txn.raw_name, txn.merchant_name):
            continue
        existing = await session.execute(
            select(Paycheck).where(Paycheck.transaction_id == txn.id)
        )
        if existing.scalar_one_or_none():
            continue
        session.add(Paycheck(
            user_id=user.id,
            transaction_id=txn.id,
            amount=abs(float(txn.amount)),
            source=extract_payroll_source(txn.raw_name, txn.merchant_name),
        ))
        paychecks_created += 1

    await session.flush()

    # ── 5. Recalculate FinancialState ─────────────────────────────────────────
    acct_result = await session.execute(
        select(Account).where(Account.user_id == user.id)
    )
    accounts = acct_result.scalars().all()

    liquid = 0.0
    for acct in accounts:
        if "depository" not in acct.type:
            continue
        bal = await session.execute(
            select(AccountBalance.current)
            .where(AccountBalance.account_id == acct.id)
            .order_by(AccountBalance.snapshot_at.desc())
            .limit(1)
        )
        val = bal.scalar_one_or_none()
        if val is not None:
            liquid += float(val)

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
    recent = [t for t in all_txns if not t.pending and t.posted_at >= cutoff]

    monthly_income = 0.0
    monthly_expenses = 0.0
    for txn in recent:
        amt = float(txn.amount)
        if amt < 0 or txn.category_primary == "INCOME":
            monthly_income += abs(amt)
        elif amt > 0:
            monthly_expenses += amt

    emergency_score = (liquid / monthly_expenses) if monthly_expenses > 0 else None

    # Pay frequency from paycheck history
    pc_result = await session.execute(
        select(Paycheck).where(Paycheck.user_id == user.id)
        .order_by(Paycheck.detected_at.desc()).limit(12)
    )
    paychecks = pc_result.scalars().all()
    last_paycheck_amount = float(paychecks[0].amount) if paychecks else None
    pay_frequency = None
    if len(paychecks) >= 2:
        txn_ids = [p.transaction_id for p in paychecks]
        dates_result = await session.execute(
            select(Transaction.posted_at).where(Transaction.id.in_(txn_ids))
        )
        pay_frequency = detect_pay_frequency(list(dates_result.scalars().all()))

    state_result = await session.execute(
        select(FinancialState).where(FinancialState.user_id == user.id)
    )
    state = state_result.scalar_one_or_none()
    if state:
        state.total_liquid_balance = liquid
        state.monthly_income_est = monthly_income or None
        state.monthly_expenses_est = monthly_expenses or None
        state.emergency_fund_score = emergency_score
        state.last_paycheck_amount = last_paycheck_amount
        state.pay_frequency = pay_frequency
    else:
        session.add(FinancialState(
            user_id=user.id,
            total_liquid_balance=liquid,
            monthly_income_est=monthly_income or None,
            monthly_expenses_est=monthly_expenses or None,
            emergency_fund_score=emergency_score,
            last_paycheck_amount=last_paycheck_amount,
            pay_frequency=pay_frequency,
        ))

    return {
        "user": str(getattr(user, "email", user.id)),
        "transactions": len(all_txns),
        "reclassified": reclassified,
        "paychecks_created": paychecks_created,
        "monthly_income": monthly_income,
        "monthly_expenses": monthly_expenses,
        "liquid_balance": liquid,
        "pay_frequency": pay_frequency,
    }


async def main():
    async with AsyncSessionLocal() as session:
        users_result = await session.execute(select(User))
        users = users_result.scalars().all()

        if not users:
            print("No users found.")
            return

        print(f"Processing {len(users)} user(s)...\n")
        for user in users:
            print(f"User: {getattr(user, 'email', user.id)}")
            result = await reclassify_user(session, user)
            print(f"  transactions : {result['transactions']}")
            print(f"  reclassified : {result['reclassified']}")
            print(f"  paychecks    : {result['paychecks_created']} new records")
            print(f"  monthly income  : ${result['monthly_income']:,.2f}")
            print(f"  monthly expenses: ${result['monthly_expenses']:,.2f}")
            print(f"  liquid balance  : ${result['liquid_balance']:,.2f}")
            print(f"  pay frequency   : {result['pay_frequency'] or 'unknown'}")
            print()

        await session.commit()
        print("Done. Financial state updated.")


if __name__ == "__main__":
    asyncio.run(main())
