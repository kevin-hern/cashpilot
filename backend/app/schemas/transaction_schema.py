from pydantic import BaseModel
import uuid
from datetime import date, datetime


class TransactionOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    plaid_transaction_id: str
    amount: float
    currency: str
    merchant_name: str | None
    category_primary: str | None
    category_detailed: str | None
    payment_channel: str | None
    pending: bool
    posted_at: date

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    limit: int


class FinancialEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    amount: float | None
    detected_at: datetime
    metadata_: dict

    model_config = {"from_attributes": True}


class FinancialStateOut(BaseModel):
    total_liquid_balance: float
    monthly_income_est: float | None
    monthly_expenses_est: float | None
    last_paycheck_amount: float | None
    last_paycheck_at: datetime | None
    next_paycheck_est_at: datetime | None
    pay_frequency: str | None
    emergency_fund_score: float | None
    updated_at: datetime

    model_config = {"from_attributes": True}
