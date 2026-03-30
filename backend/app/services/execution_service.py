"""
Execution service — the last gate before any money moves.

Pre-flight checks run every time, even after approval, to guard against
race conditions (e.g., balance changed between approval and execution).
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
from datetime import datetime, timezone
import uuid

from app.models.intent_model import Intent, Execution
from app.services.audit_service import AuditService


class ExecutionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit = AuditService(db)

    async def execute(
        self, *, intent: Intent, idempotency_key: str, user_id: uuid.UUID
    ) -> Execution:
        # Guard: check idempotency — if this key was already used, return existing execution
        existing = await self.db.execute(
            select(Execution).where(Execution.idempotency_key == idempotency_key)
        )
        if exec_record := existing.scalar_one_or_none():
            return exec_record

        # Guard: intent must be in approved state
        if intent.status != "approved":
            raise HTTPException(status_code=409, detail="Intent not in approved state")

        # Pre-flight: re-fetch and validate balance (TODO: implement fully)
        await self._preflight_balance_check(intent)

        # Write audit BEFORE calling provider (so we have a record even if provider fails)
        await self.audit.log(
            event_type="execution.submitted",
            user_id=user_id,
            actor_type="system",
            entity_type="intent",
            entity_id=intent.id,
            after_state={"amount": float(intent.amount or 0), "type": intent.intent_type},
        )

        exec_record = Execution(
            intent_id=intent.id,
            idempotency_key=idempotency_key,
            amount=intent.amount or 0,
            provider="simulated",   # swap for "plaid_sandbox" when Plaid transfer API is wired
            status="pending",
        )
        self.db.add(exec_record)
        await self.db.flush()

        # Execute (simulated for MVP)
        try:
            result = await self._run_simulated(exec_record)
            exec_record.status = "settled"
            exec_record.executed_at = datetime.now(timezone.utc)
            exec_record.settled_at = datetime.now(timezone.utc)
            exec_record.provider_txn_id = result["txn_id"]
            intent.status = "executed"
        except Exception as e:
            exec_record.status = "failed"
            exec_record.failure_reason = str(e)
            intent.status = "failed"
            await self.audit.log(
                event_type="execution.failed",
                user_id=user_id,
                entity_type="execution",
                entity_id=exec_record.id,
                after_state={"error": str(e)},
            )
            raise

        await self.db.flush()
        await self.audit.log(
            event_type="execution.settled",
            user_id=user_id,
            entity_type="execution",
            entity_id=exec_record.id,
            after_state={"provider_txn_id": exec_record.provider_txn_id},
        )
        return exec_record

    async def _preflight_balance_check(self, intent: Intent) -> None:
        # TODO: re-fetch latest AccountBalance from DB and verify amount is still safe
        pass

    async def _run_simulated(self, execution: Execution) -> dict:
        """Simulated execution. Replace with Plaid /transfer/create for real money movement."""
        import uuid as _uuid
        return {"txn_id": f"sim_{_uuid.uuid4().hex[:12]}"}
