import uuid
from datetime import datetime, date
from sqlalchemy import String, Date, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base


class Paycheck(Base):
    """
    Each row represents a single confirmed paycheck deposit.
    Populated by the classification service during ingestion and re-classification.
    """
    __tablename__ = "paychecks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), unique=True, nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)   # always positive
    source: Mapped[str | None] = mapped_column(String(255))                 # "GUSTO", "ADP", etc.
    pay_frequency: Mapped[str | None] = mapped_column(String(20))           # weekly|biweekly|semimonthly|monthly|irregular
    pay_period_start: Mapped[date | None] = mapped_column(Date)
    pay_period_end: Mapped[date | None] = mapped_column(Date)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transaction: Mapped["Transaction"] = relationship("Transaction")
