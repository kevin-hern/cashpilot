from pydantic import BaseModel
import uuid
from datetime import datetime


class IntentOut(BaseModel):
    id: uuid.UUID
    intent_type: str
    status: str
    title: str
    explanation: str
    amount: float | None
    from_account_id: uuid.UUID | None
    to_account_id: uuid.UUID | None
    confidence_score: float | None
    generated_by: str
    expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreatePendingIntentRequest(BaseModel):
    """Creates an intent with status pending_approval (no execution yet)."""
    intent_type: str
    title: str
    explanation: str
    amount: float | None = None
    confidence: float | None = None


class ChatIntentRequest(BaseModel):
    """Used when approving an intent surfaced directly in chat (no pre-existing DB record)."""
    intent_type: str
    title: str
    explanation: str
    amount: float | None = None
    confidence: float | None = None
    idempotency_key: str   # client-generated UUID, prevents double-execution


class ApproveRequest(BaseModel):
    idempotency_key: str    # client-generated UUID, prevents double-execution


class RejectRequest(BaseModel):
    reason: str | None = None


class ExecutionOut(BaseModel):
    id: uuid.UUID
    intent_id: uuid.UUID
    status: str
    provider: str
    provider_txn_id: str | None
    amount: float
    executed_at: datetime | None
    settled_at: datetime | None

    model_config = {"from_attributes": True}
