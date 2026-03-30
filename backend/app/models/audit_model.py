import uuid
from datetime import datetime
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base


class AuditLog(Base):
    """Append-only audit log. Never UPDATE or DELETE rows from this table."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)     # user|system|llm|webhook
    actor_id: Mapped[str | None] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # namespaced: intent.created | approval.actioned | execution.submitted | plaid.linked
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    before_state: Mapped[dict | None] = mapped_column(JSON)
    after_state: Mapped[dict | None] = mapped_column(JSON)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    ip_hash: Mapped[str | None] = mapped_column(String(64))                 # SHA-256 hashed IP
    request_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
