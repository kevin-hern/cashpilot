"""
Plaid integration service.
Wraps the Plaid Python client (v38+) and handles token encryption/decryption.

v38 API notes:
- Response objects use dot notation (.link_token), not dict notation (["link_token"])
- expiration is a datetime object — convert to ISO string for API responses
- Environment.Development was removed; sandbox covers dev use
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
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
from datetime import timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import uuid

from app.core.config import settings
from app.models.user_model import User
from app.models.plaid_model import PlaidItem, Account, AccountBalance
from app.models.transaction_model import Transaction, FinancialState
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
        response = self.client.link_token_create(request)
        # v38: response is an object with dot-notation attributes
        # expiration is datetime — convert to ISO string
        expiration = response.expiration
        return LinkTokenResponse(
            link_token=response.link_token,
            expiration=expiration.isoformat() if hasattr(expiration, "isoformat") else str(expiration),
        )

    async def exchange_public_token(self, user: User, body: ExchangeRequest) -> ExchangeResponse:
        exchange_resp = self.client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=body.public_token)
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
        try:
            access_token = _decrypt_token(item.access_token_enc)
            self.client.item_remove(ItemRemoveRequest(access_token=access_token))
        except Exception:
            pass  # Best-effort revocation
        item.status = "revoked"

    async def trigger_sync(self, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(PlaidItem).where(PlaidItem.id == item_id, PlaidItem.user_id == user_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        access_token = _decrypt_token(item.access_token_enc)

        # Fetch accounts to build plaid_account_id → internal UUID map
        accounts_resp = self.client.accounts_get(AccountsGetRequest(access_token=access_token))
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

        # Page through transactions/sync cursor
        cursor = item.cursor
        added: list[dict] = []
        while True:
            kwargs: dict = dict(access_token=access_token)
            if cursor:
                kwargs["cursor"] = cursor
            resp = self.client.transactions_sync(TransactionsSyncRequest(**kwargs))
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
        for raw in added:
            existing = await self.db.execute(
                select(Transaction).where(Transaction.plaid_transaction_id == raw["transaction_id"])
            )
            txn = existing.scalar_one_or_none()
            if txn:
                txn.pending = raw["pending"]
                txn.amount = raw["amount"]
            else:
                internal_acct_id = account_map.get(raw["account_id"])
                if not internal_acct_id:
                    continue
                txn = Transaction(
                    user_id=user_id,
                    account_id=internal_acct_id,
                    plaid_transaction_id=raw["transaction_id"],
                    amount=raw["amount"],
                    currency=raw.get("iso_currency_code", "USD"),
                    merchant_name=raw.get("merchant_name"),
                    raw_name=raw.get("name"),
                    category_primary=raw.get("personal_finance_category", {}).get("primary"),
                    category_detailed=raw.get("personal_finance_category", {}).get("detailed"),
                    payment_channel=raw.get("payment_channel"),
                    pending=raw.get("pending", False),
                    posted_at=raw["date"],
                    metadata_={"plaid_raw": {}},
                )
                self.db.add(txn)

        await self.db.flush()
        await self._recalculate_financial_state(user_id, db_accounts)

    async def _recalculate_financial_state(self, user_id: uuid.UUID, db_accounts: dict) -> None:
        from datetime import datetime, timedelta
        from sqlalchemy import func as sqlfunc

        # Total liquid balance = sum of latest current balance for depository accounts
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

        # Monthly income/expenses from last 30 days of non-pending transactions
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
        txn_result = await self.db.execute(
            select(Transaction.amount)
            .where(Transaction.user_id == user_id, Transaction.pending == False, Transaction.posted_at >= cutoff)
        )
        amounts = [float(r) for r in txn_result.scalars().all()]
        # In Plaid: positive amount = debit (expense), negative amount = credit (income)
        monthly_expenses = sum(a for a in amounts if a > 0)
        monthly_income = sum(-a for a in amounts if a < 0)

        emergency_score = (liquid / monthly_expenses) if monthly_expenses > 0 else None

        state_result = await self.db.execute(
            select(FinancialState).where(FinancialState.user_id == user_id)
        )
        state = state_result.scalar_one_or_none()
        if state:
            state.total_liquid_balance = liquid
            state.monthly_income_est = monthly_income or None
            state.monthly_expenses_est = monthly_expenses or None
            state.emergency_fund_score = emergency_score
        else:
            state = FinancialState(
                user_id=user_id,
                total_liquid_balance=liquid,
                monthly_income_est=monthly_income or None,
                monthly_expenses_est=monthly_expenses or None,
                emergency_fund_score=emergency_score,
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
        for acct in resp.accounts:
            account = Account(
                user_id=item.user_id,
                plaid_item_id=item.id,
                plaid_account_id=acct.account_id,
                name=acct.name,
                official_name=getattr(acct, "official_name", None),
                type=str(acct.type),
                subtype=str(acct.subtype) if acct.subtype else None,
            )
            self.db.add(account)
            await self.db.flush()
            balances = acct.balances
            balance = AccountBalance(
                account_id=account.id,
                available=getattr(balances, "available", None),
                current=balances.current,
                limit_amount=getattr(balances, "limit", None),
            )
            self.db.add(balance)
