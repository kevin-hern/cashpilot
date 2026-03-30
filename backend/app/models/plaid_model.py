import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base


class PlaidItem(Base):
    __tablename__ = "plaid_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plaid_item_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    access_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # AES-256-GCM encrypted
    institution_id: Mapped[str | None] = mapped_column(String(100))
    institution_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")   # active|error|revoked
    error_code: Mapped[str | None] = mapped_column(String(100))
    consent_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[str | None] = mapped_column(String(512))             # Plaid sync cursor
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="plaid_items")
    accounts: Mapped[list["Account"]] = relationship("Account", back_populates="plaid_item")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    plaid_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plaid_items.id"), nullable=False)
    plaid_account_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    official_name: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50), nullable=False)       # depository|credit|loan|investment
    subtype: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="accounts")
    plaid_item: Mapped["PlaidItem"] = relationship("PlaidItem", back_populates="accounts")
    balances: Mapped[list["AccountBalance"]] = relationship("AccountBalance", back_populates="account")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="account")


class AccountBalance(Base):
    __tablename__ = "account_balances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True)
    available: Mapped[float | None] = mapped_column()
    current: Mapped[float] = mapped_column(nullable=False)
    limit_amount: Mapped[float | None] = mapped_column()
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    account: Mapped["Account"] = relationship("Account", back_populates="balances")
