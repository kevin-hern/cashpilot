"""
Approval service — manages the intent lifecycle from pending → approved/rejected → executed.

SAFETY CONTRACT:
  No execution can happen without:
  1. Intent in 'pending_approval' status
  2. Explicit user approval action recorded
  3. Pre-flight balance re-validation
  4. Unique idempotency_key
  5. Audit entry written BEFORE execution call
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, Request
import uuid

from app.models.intent_model import Intent, ApprovalAction, Execution
from app.services.audit_service import AuditService
from app.services.execution_service import ExecutionService
from app.models.user_model import User


class ApprovalService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit = AuditService(db)

    async def list_intents(
        self,
        user_id: uuid.UUID,
        statuses: list[str] | None = None,
    ) -> list[Intent]:
        query = select(Intent).where(Intent.user_id == user_id)
        if statuses:
            query = query.where(Intent.status.in_(statuses))
        query = query.order_by(Intent.created_at.desc()).limit(100)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def list_pending(self, user_id: uuid.UUID) -> list[Intent]:
        return await self.list_intents(user_id, statuses=["pending_approval"])

    async def get_intent(self, user_id: uuid.UUID, intent_id: uuid.UUID) -> Intent | None:
        result = await self.db.execute(
            select(Intent).where(Intent.id == intent_id, Intent.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def approve(
        self,
        user: User,
        intent_id: uuid.UUID,
        idempotency_key: str,
        request: Request,
    ) -> Execution:
        intent = await self.get_intent(user.id, intent_id)
        if not intent:
            raise HTTPException(status_code=404, detail="Intent not found")
        if intent.status != "pending_approval":
            raise HTTPException(status_code=409, detail=f"Intent is already {intent.status}")

        # Record approval action
        action = ApprovalAction(
            intent_id=intent.id,
            user_id=user.id,
            action="approve",
            device_info={"user_agent": request.headers.get("user-agent", ""), "ip": "hashed"},
        )
        self.db.add(action)
        intent.status = "approved"
        await self.db.flush()

        await self.audit.log(
            event_type="approval.actioned",
            user_id=user.id,
            actor_type="user",
            actor_id=str(user.id),
            entity_type="intent",
            entity_id=intent.id,
            before_state={"status": "pending_approval"},
            after_state={"status": "approved"},
        )

        # Trigger execution (audit entry written inside execute())
        exec_svc = ExecutionService(self.db)
        return await exec_svc.execute(intent=intent, idempotency_key=idempotency_key, user_id=user.id)

    async def reject(self, user_id: uuid.UUID, intent_id: uuid.UUID, reason: str | None = None) -> None:
        intent = await self.get_intent(user_id, intent_id)
        if not intent:
            raise HTTPException(status_code=404, detail="Intent not found")
        if intent.status != "pending_approval":
            raise HTTPException(status_code=409, detail=f"Intent is already {intent.status}")

        action = ApprovalAction(
            intent_id=intent.id,
            user_id=user_id,
            action="reject",
            reason=reason,
        )
        self.db.add(action)
        intent.status = "rejected"
        await self.db.flush()

        await self.audit.log(
            event_type="approval.actioned",
            user_id=user_id,
            actor_type="user",
            actor_id=str(user_id),
            entity_type="intent",
            entity_id=intent.id,
            before_state={"status": "pending_approval"},
            after_state={"status": "rejected", "reason": reason},
        )
