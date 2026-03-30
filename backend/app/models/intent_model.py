import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Numeric, JSON, ARRAY, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base


class Intent(Base):
    __tablename__ = "intents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    triggering_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("financial_events.id"))
    intent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # transfer_to_savings|pay_bill|invest|alert|suggestion
    status: Mapped[str] = mapped_column(String(30), default="pending_approval", index=True)
    # pending_approval|approved|rejected|expired|executed|failed|cancelled
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    explanation: Mapped[str] = mapped_column(String(2000), nullable=False)
    amount: Mapped[float | None] = mapped_column(Numeric(15, 2))
    from_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"))
    to_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"))
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    generated_by: Mapped[str] = mapped_column(String(30), nullable=False)   # rules_engine|llm|hybrid
    rule_ids_fired: Mapped[list | None] = mapped_column(JSON)
    llm_model: Mapped[str | None] = mapped_column(String(100))
    llm_prompt_hash: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="intents")
    approval_actions: Mapped[list["ApprovalAction"]] = relationship("ApprovalAction", back_populates="intent")
    execution: Mapped["Execution | None"] = relationship("Execution", back_populates="intent", uselist=False)


class ApprovalAction(Base):
    __tablename__ = "approval_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("intents.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)     # approve|reject|modify
    reason: Mapped[str | None] = mapped_column(String(500))
    device_info: Mapped[dict] = mapped_column(JSON, default=dict)
    actioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    intent: Mapped["Intent"] = relationship("Intent", back_populates="approval_actions")


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("intents.id"), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending|submitted|settled|failed|reversed
    provider: Mapped[str] = mapped_column(String(50), nullable=False)   # plaid_sandbox|simulated
    provider_txn_id: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    intent: Mapped["Intent"] = relationship("Intent", back_populates="execution")
