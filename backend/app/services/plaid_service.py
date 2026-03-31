"""
Plaid integration service.
Wraps the Plaid Python client (v38+) and handles token encryption/decryption.

v38 API notes:
- Response objects use dot notation (.link_token), not dict notation (["link_token"])
- expiration is a datetime object — convert to ISO string for API responses
- Environment.Development was removed; sandbox covers dev use
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from fastapi import HTTPException
from app.models.transaction_model import FinancialEvent
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
import os
import asyncio
from datetime import timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import uuid

from app.core.config import settings
from app.models.user_model import User
from app.models.plaid_model import PlaidItem, Account, AccountBalance
from app.models.transaction_model import Transaction, FinancialState
from app.models.paycheck_model import Paycheck
from app.services.classification_service import (
    normalize_category, is_paycheck, extract_payroll_source, detect_pay_frequency,
)
from app.schemas.plaid_schema import (
    LinkTokenResponse, ExchangeRequest, ExchangeResponse, PlaidWebhookPayload
)

PLAID_ENV_MAP = {
    "sandbox": plaid.Environment.Sandbox,
    "development": plaid.Environment.Sandbox,   # v38 removed Development
    "production": plaid.Environment.Production,
}


def _get_plaid_client() -> plaid_api.PlaidApi:
    configuration = plaid.Configuration(
        host=PLAID_ENV_MAP[settings.PLAID_ENV],
        api_key={"clientId": settings.PLAID_CLIENT_ID, "secret": settings.PLAID_SECRET},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def _encrypt_token(token: str) -> bytes:
    key = bytes.fromhex(settings.ENCRYPTION_KEY)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, token.encode(), None)
    return nonce + ct


def _decrypt_token(blob: bytes) -> str:
    key = bytes.fromhex(settings.ENCRYPTION_KEY)
    aesgcm = AESGCM(key)
    nonce, ct = blob[:12], blob[12:]
    return aesgcm.decrypt(nonce, ct, None).decode()


class PlaidService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.client = _get_plaid_client()

    async def create_link_token(self, user: User) -> LinkTokenResponse:
        kwargs: dict = dict(
            user=LinkTokenCreateRequestUser(client_user_id=str(user.id)),
            client_name="CashPilot",
            products=[Products("transactions")],
            country_codes=[CountryCode("US")],
            language="en",
        )
        # Only pass webhook if it's a real URL (Plaid v38 rejects None)
        if settings.PLAID_WEBHOOK_URL and settings.PLAID_WEBHOOK_URL.startswith("https://"):
            kwargs["webhook"] = settings.PLAID_WEBHOOK_URL
        request = LinkTokenCreateRequest(**kwargs)
        response = await asyncio.to_thread(self.client.link_token_create, request)
        # v38: response is an object with dot-notation attributes
        # expiration is datetime — convert to ISO string
        expiration = response.expiration
        return LinkTokenResponse(
            link_token=response.link_token,
            expiration=expiration.isoformat() if hasattr(expiration, "isoformat") else str(expiration),
        )

    async def exchange_public_token(self, user: User, body: ExchangeRequest) -> ExchangeResponse:
        exchange_resp = await asyncio.to_thread(
            self.client.item_public_token_exchange,
            ItemPublicTokenExchangeRequest(public_token=body.public_token),
        )
        # v38: dot notation
        access_token = exchange_resp.access_token
        plaid_item_id = exchange_resp.item_id

        item = PlaidItem(
            user_id=user.id,
            plaid_item_id=plaid_item_id,
            access_token_enc=_encrypt_token(access_token),
            institution_id=body.institution_id,
            institution_name=body.institution_name,
        )
        self.db.add(item)
        await self.db.flush()

        await self._sync_accounts(item, access_token)

        return ExchangeResponse(item_id=item.id, institution_name=item.institution_name)

    async def list_items(self, user_id: uuid.UUID) -> list[PlaidItem]:
        result = await self.db.execute(
            select(PlaidItem).where(PlaidItem.user_id == user_id, PlaidItem.status == "active")
        )
        return result.scalars().all()

    async def unlink_item(self, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(PlaidItem).where(PlaidItem.id == item_id, PlaidItem.user_id == user_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        # Best-effort revocation with Plaid (don't fail if Plaid is down)
        try:
            access_token = _decrypt_token(item.access_token_enc)
            await asyncio.to_thread(
                self.client.item_remove, ItemRemoveRequest(access_token=access_token)
            )
        except Exception:
            pass

        # Collect account IDs for this item
        acct_result = await self.db.execute(
            select(Account.id).where(Account.plaid_item_id == item_id)
        )
        account_ids = [r for r in acct_result.scalars().all()]

        if account_ids:
            # Collect transaction IDs for these accounts
            txn_result = await self.db.execute(
                select(Transaction.id).where(Transaction.account_id.in_(account_ids))
            )
            transaction_ids = [r for r in txn_result.scalars().all()]

            if transaction_ids:
                # Delete paychecks referencing these transactions
                await self.db.execute(
                    delete(Paycheck).where(Paycheck.transaction_id.in_(transaction_ids))
                )
                # Delete financial events referencing these transactions
                await self.db.execute(
                    delete(FinancialEvent).where(FinancialEvent.transaction_id.in_(transaction_ids))
                )
                # Delete transactions
                await self.db.execute(
                    delete(Transaction).where(Transaction.id.in_(transaction_ids))
                )

            # Delete financial events referencing these accounts (no transaction)
            await self.db.execute(
                delete(FinancialEvent).where(FinancialEvent.account_id.in_(account_ids))
            )
            # Delete account balances
            await self.db.execute(
                delete(AccountBalance).where(AccountBalance.account_id.in_(account_ids))
            )
            # Delete accounts
            await self.db.execute(
                delete(Account).where(Account.id.in_(account_ids))
            )

        # Delete the item itself
        await self.db.execute(
            delete(PlaidItem).where(PlaidItem.id == item_id)
        )

    async def trigger_sync(self, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(PlaidItem).where(PlaidItem.id == item_id, PlaidItem.user_id == user_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        access_token = _decrypt_token(item.access_token_enc)

        # Fetch accounts to build plaid_account_id → internal UUID map.
        # Run the synchronous Plaid SDK call in a thread so it doesn't block
        # the async event loop (prevents Railway from timing out the connection).
        accounts_resp = await asyncio.to_thread(
            self.client.accounts_get, AccountsGetRequest(access_token=access_token)
        )
        acct_result = await self.db.execute(
            select(Account).where(Account.plaid_item_id == item.id)
        )
        db_accounts = {a.plaid_account_id: a for a in acct_result.scalars().all()}

        # Refresh balances
        for acct in accounts_resp.accounts:
            db_acct = db_accounts.get(acct.account_id)
            if db_acct:
                balance = AccountBalance(
                    account_id=db_acct.id,
                    available=getattr(acct.balances, "available", None),
                    current=acct.balances.current,
                    limit_amount=getattr(acct.balances, "limit", None),
                )
                self.db.add(balance)

        # Page through transactions/sync cursor (each page is a blocking call —
        # run in thread to keep the async event loop free).
        cursor = item.cursor
        added: list[dict] = []
        while True:
            kwargs: dict = dict(access_token=access_token)
            if cursor:
                kwargs["cursor"] = cursor
            resp = await asyncio.to_thread(
                self.client.transactions_sync, TransactionsSyncRequest(**kwargs)
            )
            for t in resp.added:
                added.append({
                    "transaction_id": t.transaction_id,
                    "account_id": t.account_id,
                    "amount": float(t.amount),
                    "iso_currency_code": getattr(t, "iso_currency_code", "USD"),
                    "merchant_name": getattr(t, "merchant_name", None),
                    "name": getattr(t, "name", None),
                    "personal_finance_category": {
                        "primary": getattr(t.personal_finance_category, "primary", None),
                        "detailed": getattr(t.personal_finance_category, "detailed", None),
                    } if getattr(t, "personal_finance_category", None) else {},
                    "payment_channel": getattr(t, "payment_channel", None),
                    "pending": getattr(t, "pending", False),
                    "date": t.date,
                })
            cursor = resp.next_cursor
            if not resp.has_more:
                break

        # Update cursor and last_synced_at
        from datetime import datetime
        item.cursor = cursor
        item.last_synced_at = datetime.now(timezone.utc)

        # Upsert transactions
        account_map = {plaid_id: acct.id for plaid_id, acct in db_accounts.items()}
        new_txns: list[Transaction] = []
        for raw in added:
            raw_name = raw.get("name")
            merchant_name = raw.get("merchant_name")
            plaid_cat = raw.get("personal_finance_category", {}).get("primary")
            amount = raw["amount"]

            # Normalize category — fixes GUSTO/ADP mis-classified as RENT_AND_UTILITIES
            corrected_category = normalize_category(raw_name, merchant_name, plaid_cat, amount)

            existing = await self.db.execute(
                select(Transaction).where(Transaction.plaid_transaction_id == raw["transaction_id"])
            )
            txn = existing.scalar_one_or_none()
            if txn:
                txn.pending = raw["pending"]
                txn.amount = amount
                # Re-apply classification on update too
                txn.category_primary = normalize_category(
                    txn.raw_name, txn.merchant_name, txn.category_primary, float(txn.amount)
                )
            else:
                internal_acct_id = account_map.get(raw["account_id"])
                if not internal_acct_id:
                    continue
                txn = Transaction(
                    user_id=user_id,
                    account_id=internal_acct_id,
                    plaid_transaction_id=raw["transaction_id"],
                    amount=amount,
                    currency=raw.get("iso_currency_code", "USD"),
                    merchant_name=merchant_name,
                    raw_name=raw_name,
                    category_primary=corrected_category,
                    category_detailed=raw.get("personal_finance_category", {}).get("detailed"),
                    payment_channel=raw.get("payment_channel"),
                    pending=raw.get("pending", False),
                    posted_at=raw["date"],
                    metadata_={"plaid_raw": {}},
                )
                self.db.add(txn)
                new_txns.append(txn)

        await self.db.flush()

        # Upsert Paycheck records for newly detected paychecks
        for txn in new_txns:
            if is_paycheck(float(txn.amount), txn.category_primary, txn.raw_name, txn.merchant_name):
                existing_pc = await self.db.execute(
                    select(Paycheck).where(Paycheck.transaction_id == txn.id)
                )
                if not existing_pc.scalar_one_or_none():
                    self.db.add(Paycheck(
                        user_id=user_id,
                        transaction_id=txn.id,
                        amount=abs(float(txn.amount)),
                        source=extract_payroll_source(txn.raw_name, txn.merchant_name),
                    ))

        await self.db.flush()
        await self._recalculate_financial_state(user_id, db_accounts)

    async def _recalculate_financial_state(self, user_id: uuid.UUID, db_accounts: dict) -> None:
        from datetime import datetime, timedelta

        # ── Liquid balance ────────────────────────────────────────────────────
        depository_ids = [a.id for a in db_accounts.values() if "depository" in a.type]
        liquid = 0.0
        for acct_id in depository_ids:
            row = await self.db.execute(
                select(AccountBalance.current)
                .where(AccountBalance.account_id == acct_id)
                .order_by(AccountBalance.snapshot_at.desc())
                .limit(1)
            )
            val = row.scalar_one_or_none()
            if val is not None:
                liquid += float(val)

        # ── Income & expenses (last 30 days, non-pending) ─────────────────────
        # Fetch full transaction rows so we can apply category-aware income logic.
        # Income rule:
        #   - amount < 0  (standard Plaid credit/income)
        #   - OR category_primary == "INCOME" (handles Plaid sandbox edge cases
        #     where payroll arrives as positive amount but correctly categorized)
        # Expense rule:
        #   - amount > 0 AND category_primary not in ("INCOME")
        #   This prevents mis-categorized payroll from inflating expenses.
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
        txn_result = await self.db.execute(
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.pending == False,
                Transaction.posted_at >= cutoff,
            )
        )
        transactions = txn_result.scalars().all()

        monthly_income = 0.0
        monthly_expenses = 0.0
        for txn in transactions:
            amt = float(txn.amount)
            is_income = (amt < 0) or (txn.category_primary == "INCOME")
            if is_income:
                monthly_income += abs(amt)
            elif amt > 0:
                monthly_expenses += amt

        emergency_score = (liquid / monthly_expenses) if monthly_expenses > 0 else None

        # ── Paycheck-derived fields ───────────────────────────────────────────
        pc_result = await self.db.execute(
            select(Paycheck)
            .where(Paycheck.user_id == user_id)
            .order_by(Paycheck.detected_at.desc())
            .limit(12)
        )
        paychecks = pc_result.scalars().all()
        last_paycheck_amount = float(paychecks[0].amount) if paychecks else None
        pay_frequency = None
        if len(paychecks) >= 2:
            # fetch posted_at from linked transactions
            txn_ids = [p.transaction_id for p in paychecks]
            dates_result = await self.db.execute(
                select(Transaction.posted_at).where(Transaction.id.in_(txn_ids))
            )
            pay_dates = [r for r in dates_result.scalars().all()]
            pay_frequency = detect_pay_frequency(pay_dates)

        # ── Upsert FinancialState ─────────────────────────────────────────────
        state_result = await self.db.execute(
            select(FinancialState).where(FinancialState.user_id == user_id)
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
            state = FinancialState(
                user_id=user_id,
                total_liquid_balance=liquid,
                monthly_income_est=monthly_income or None,
                monthly_expenses_est=monthly_expenses or None,
                emergency_fund_score=emergency_score,
                last_paycheck_amount=last_paycheck_amount,
                pay_frequency=pay_frequency,
            )
            self.db.add(state)

    async def verify_webhook_signature(self, body: bytes, header: str | None) -> bool:
        if settings.PLAID_ENV == "sandbox":
            return True
        return header is not None

    async def enqueue_webhook(self, payload: PlaidWebhookPayload) -> None:
        # TODO: push to Redis Stream for async processing
        pass

    async def _sync_accounts(self, item: PlaidItem, access_token: str) -> None:
        resp = self.client.accounts_get(AccountsGetRequest(access_token=access_token))
        # v38: resp.accounts is a list of AccountBase objects with dot notation

        # First, purge any duplicate rows that snuck in before this fix —
        # keep the oldest row (MIN id) per plaid_account_id.
        min_ids = (
            select(func.min(Account.id).label("keep_id"))
            .where(Account.user_id == item.user_id)
            .group_by(Account.plaid_account_id)
            .subquery()
        )
        await self.db.execute(
            delete(Account).where(
                Account.user_id == item.user_id,
                Account.id.not_in(select(min_ids.c.keep_id)),
            )
        )
        await self.db.flush()

        for acct in resp.accounts:
            # INSERT … ON CONFLICT DO UPDATE (true upsert — no race condition)
            stmt = (
                pg_insert(Account)
                .values(
                    user_id=item.user_id,
                    plaid_item_id=item.id,
                    plaid_account_id=acct.account_id,
                    name=acct.name,
                    official_name=getattr(acct, "official_name", None),
                    type=str(acct.type),
                    subtype=str(acct.subtype) if acct.subtype else None,
                )
                .on_conflict_do_update(
                    index_elements=["plaid_account_id"],
                    set_={
                        "name": acct.name,
                        "official_name": getattr(acct, "official_name", None),
                        "subtype": str(acct.subtype) if acct.subtype else None,
                    },
                )
                .returning(Account.id)
            )
            result = await self.db.execute(stmt)
            account_id = result.scalar_one()
            await self.db.flush()

            balances = acct.balances
            balance = AccountBalance(
                account_id=account_id,
                available=getattr(balances, "available", None),
                current=balances.current,
                limit_amount=getattr(balances, "limit", None),
            )
            self.db.add(balance)
