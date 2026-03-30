from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import uuid
import hashlib

from app.models.audit_model import AuditLog


class AuditService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(
        self,
        *,
        event_type: str,
        actor_type: str = "system",
        actor_id: str | None = None,
        user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        before_state: dict | None = None,
        after_state: dict | None = None,
        metadata: dict | None = None,
        ip: str | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        """Append an immutable audit entry. Never call UPDATE/DELETE on audit_log."""
        entry = AuditLog(
            user_id=user_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            before_state=before_state,
            after_state=after_state,
            metadata_=metadata or {},
            ip_hash=hashlib.sha256(ip.encode()).hexdigest() if ip else None,
            request_id=request_id,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
    ) -> list[AuditLog]:
        query = select(AuditLog).where(AuditLog.user_id == user_id)
        if entity_type:
            query = query.where(AuditLog.entity_type == entity_type)
        if entity_id:
            query = query.where(AuditLog.entity_id == entity_id)
        if start:
            query = query.where(AuditLog.created_at >= start)
        if end:
            query = query.where(AuditLog.created_at <= end)
        query = query.order_by(AuditLog.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()
