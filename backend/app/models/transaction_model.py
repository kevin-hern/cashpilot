import uuid
from datetime import datetime, date
from sqlalchemy import String, Boolean, Date, DateTime, ForeignKey, Numeric, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True)
    plaid_transaction_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)   # negative = credit (income)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    raw_name: Mapped[str | None] = mapped_column(String(255))
    category_primary: Mapped[str | None] = mapped_column(String(100), index=True)
    category_detailed: Mapped[str | None] = mapped_column(String(100))
    payment_channel: Mapped[str | None] = mapped_column(String(50))         # online|in store|other
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    normalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    user: Mapped["User"] = relationship("User", back_populates="transactions")
    account: Mapped["Account"] = relationship("Account", back_populates="transactions")


class FinancialEvent(Base):
    __tablename__ = "financial_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # paycheck|large_deposit|large_expense|recurring_charge|low_balance|overdraft_risk
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("transactions.id"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"))
    amount: Mapped[float | None] = mapped_column(Numeric(15, 2))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class FinancialState(Base):
    __tablename__ = "financial_state"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    total_liquid_balance: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    monthly_income_est: Mapped[float | None] = mapped_column(Numeric(15, 2))
    monthly_expenses_est: Mapped[float | None] = mapped_column(Numeric(15, 2))
    last_paycheck_amount: Mapped[float | None] = mapped_column(Numeric(15, 2))
    last_paycheck_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_paycheck_est_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pay_frequency: Mapped[str | None] = mapped_column(String(20))           # weekly|biweekly|semimonthly|monthly
    emergency_fund_score: Mapped[float | None] = mapped_column(Numeric(4, 2))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
