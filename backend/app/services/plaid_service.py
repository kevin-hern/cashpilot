"""
Plaid integration service.
Wraps the Plaid Python client and handles token encryption/decryption.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
import hashlib, os, json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import uuid

from app.core.config import settings
from app.models.user_model import User
from app.models.plaid_model import PlaidItem, Account, AccountBalance
from app.schemas.plaid_schema import (
    LinkTokenResponse, ExchangeRequest, ExchangeResponse, PlaidWebhookPayload
)

PLAID_ENV_MAP = {
    "sandbox": plaid.Environment.Sandbox,
    "development": plaid.Environment.Development,
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
        request = LinkTokenCreateRequest(
            user=LinkTokenCreateRequestUser(client_user_id=str(user.id)),
            client_name="CashPilot",
            products=[Products("transactions")],
            country_codes=[CountryCode("US")],
            language="en",
            webhook=settings.PLAID_WEBHOOK_URL or None,
        )
        response = self.client.link_token_create(request)
        return LinkTokenResponse(
            link_token=response["link_token"],
            expiration=response["expiration"],
        )

    async def exchange_public_token(self, user: User, body: ExchangeRequest) -> ExchangeResponse:
        exchange_resp = self.client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=body.public_token)
        )
        access_token = exchange_resp["access_token"]
        plaid_item_id = exchange_resp["item_id"]

        item = PlaidItem(
            user_id=user.id,
            plaid_item_id=plaid_item_id,
            access_token_enc=_encrypt_token(access_token),
            institution_id=body.institution_id,
            institution_name=body.institution_name,
        )
        self.db.add(item)
        await self.db.flush()

        # Fetch and store accounts
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
            self.client.item_remove({"access_token": access_token})
        except Exception:
            pass  # Best-effort revocation
        item.status = "revoked"

    async def trigger_sync(self, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
        # TODO: enqueue to Redis/Celery ingest_worker
        pass

    async def verify_webhook_signature(self, body: bytes, header: str | None) -> bool:
        # TODO: implement Plaid JWK-based webhook verification
        # For sandbox, skip verification
        if settings.PLAID_ENV == "sandbox":
            return True
        return header is not None

    async def enqueue_webhook(self, payload: PlaidWebhookPayload) -> None:
        # TODO: push to Redis Stream for async processing
        pass

    async def _sync_accounts(self, item: PlaidItem, access_token: str) -> None:
        from plaid.model.accounts_get_request import AccountsGetRequest
        resp = self.client.accounts_get(AccountsGetRequest(access_token=access_token))
        for acct in resp["accounts"]:
            account = Account(
                user_id=item.user_id,
                plaid_item_id=item.id,
                plaid_account_id=acct["account_id"],
                name=acct["name"],
                official_name=acct.get("official_name"),
                type=acct["type"],
                subtype=acct.get("subtype"),
            )
            self.db.add(account)
            await self.db.flush()
            balance = AccountBalance(
                account_id=account.id,
                available=acct["balances"].get("available"),
                current=acct["balances"]["current"],
                limit_amount=acct["balances"].get("limit"),
            )
            self.db.add(balance)
