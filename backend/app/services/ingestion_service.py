"""
Transaction ingestion and normalization service.
Called by the Celery ingest_worker after a Plaid webhook.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date
import uuid

from app.models.plaid_model import PlaidItem
from app.models.transaction_model import Transaction, FinancialEvent, FinancialState
from app.schemas.transaction_schema import TransactionListResponse, TransactionOut, FinancialStateOut


class IngestionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_transactions(self, raw_transactions: list[dict], user_id: uuid.UUID, account_map: dict) -> int:
        """Normalize and upsert Plaid transactions. Returns count inserted."""
        inserted = 0
        for raw in raw_transactions:
            existing = await self.db.execute(
                select(Transaction).where(Transaction.plaid_transaction_id == raw["transaction_id"])
            )
            txn = existing.scalar_one_or_none()
            if txn:
                txn.pending = raw.get("pending", False)
                txn.amount = raw["amount"]
            else:
                txn = Transaction(
                    user_id=user_id,
                    account_id=account_map[raw["account_id"]],
                    plaid_transaction_id=raw["transaction_id"],
                    amount=raw["amount"],
                    currency=raw.get("iso_currency_code", "USD"),
                    merchant_name=raw.get("merchant_name"),
                    raw_name=raw.get("name"),
                    category_primary=raw.get("personal_finance_category", {}).get("primary"),
                    category_detailed=raw.get("personal_finance_category", {}).get("detailed"),
                    payment_channel=raw.get("payment_channel"),
                    pending=raw.get("pending", False),
                    posted_at=raw.get("date"),
                    metadata_={"plaid_raw": raw},
                )
                self.db.add(txn)
                inserted += 1
        await self.db.flush()
        return inserted

    async def list_transactions(
        self,
        user_id: uuid.UUID,
        *,
        account_id: str | None = None,
        category: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        limit: int = 50,
    ) -> TransactionListResponse:
        query = select(Transaction).where(Transaction.user_id == user_id)
        if account_id:
            query = query.where(Transaction.account_id == account_id)
        if category:
            query = query.where(Transaction.category_primary == category)
        if start_date:
            query = query.where(Transaction.posted_at >= start_date)
        if end_date:
            query = query.where(Transaction.posted_at <= end_date)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_q)).scalar()

        query = query.order_by(Transaction.posted_at.desc()).offset((page - 1) * limit).limit(limit)
        rows = (await self.db.execute(query)).scalars().all()

        return TransactionListResponse(
            items=[TransactionOut.model_validate(r) for r in rows],
            total=total,
            page=page,
            limit=limit,
        )

    async def get_financial_state(self, user_id: uuid.UUID) -> FinancialStateOut:
        result = await self.db.execute(
            select(FinancialState).where(FinancialState.user_id == user_id)
        )
        state = result.scalar_one_or_none()
        if not state:
            # Return zeroed state for new users
            from datetime import datetime, timezone
            return FinancialStateOut(
                total_liquid_balance=0,
                monthly_income_est=None,
                monthly_expenses_est=None,
                last_paycheck_amount=None,
                last_paycheck_at=None,
                next_paycheck_est_at=None,
                pay_frequency=None,
                emergency_fund_score=None,
                updated_at=datetime.now(timezone.utc),
            )
        return FinancialStateOut.model_validate(state)

    async def list_events(self, user_id: uuid.UUID, limit: int = 20) -> list[FinancialEvent]:
        result = await self.db.execute(
            select(FinancialEvent)
            .where(FinancialEvent.user_id == user_id)
            .order_by(FinancialEvent.detected_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
