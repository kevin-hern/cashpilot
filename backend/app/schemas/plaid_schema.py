from pydantic import BaseModel
import uuid
from datetime import datetime


class LinkTokenResponse(BaseModel):
    link_token: str
    expiration: str


class ExchangeRequest(BaseModel):
    public_token: str
    institution_id: str | None = None
    institution_name: str | None = None


class ExchangeResponse(BaseModel):
    item_id: uuid.UUID
    institution_name: str | None


class PlaidItemOut(BaseModel):
    id: uuid.UUID
    institution_name: str | None
    status: str
    last_synced_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountOut(BaseModel):
    id: uuid.UUID
    plaid_account_id: str
    name: str
    type: str
    subtype: str | None
    currency: str
    is_primary: bool
    available_balance: float | None = None
    current_balance: float | None = None

    model_config = {"from_attributes": True}


class PlaidWebhookPayload(BaseModel):
    webhook_type: str
    webhook_code: str
    item_id: str
    error: dict | None = None
