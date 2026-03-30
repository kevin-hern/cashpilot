"""
Decision engine — orchestrates rules engine + LLM to produce structured Intents.
Runs after transaction ingestion detects financial events.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
import uuid

from app.core.config import settings
from app.models.intent_model import Intent
from app.models.transaction_model import FinancialEvent, FinancialState
from app.services.llm_service import LLMService
from app.services.audit_service import AuditService


class DecisionEngine:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLMService(db)
        self.audit = AuditService(db)

    async def run_for_user(self, user_id: uuid.UUID) -> list[Intent]:
        """Process all unhandled financial events for a user and create Intents."""
        events = await self._get_unprocessed_events(user_id)
        if not events:
            return []

        state = await self._get_state(user_id)
        pending_intents = await self._get_pending_intents(user_id)

        created = []
        for event in events:
            intent = await self._process_event(user_id, event, state, pending_intents)
            if intent:
                created.append(intent)
                pending_intents.append(intent)
            event.processed = True

        await self.db.flush()
        return created

    async def list_intents(
        self, user_id: uuid.UUID, status: str | None = None, limit: int = 20
    ) -> list[Intent]:
        query = select(Intent).where(Intent.user_id == user_id)
        if status:
            query = query.where(Intent.status == status)
        query = query.order_by(Intent.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def _process_event(
        self,
        user_id: uuid.UUID,
        event: FinancialEvent,
        state: FinancialState | None,
        pending_intents: list[Intent],
    ) -> Intent | None:
        if event.event_type == "paycheck":
            return await self._handle_paycheck(user_id, event, state, pending_intents)
        elif event.event_type == "low_balance":
            return await self._handle_low_balance(user_id, event, state)
        return None

    async def _handle_paycheck(
        self,
        user_id: uuid.UUID,
        event: FinancialEvent,
        state: FinancialState | None,
        pending_intents: list[Intent],
    ) -> Intent | None:
        # Don't duplicate: skip if a savings intent is already pending
        if any(i.intent_type == "transfer_to_savings" for i in pending_intents):
            return None

        paycheck_amount = abs(float(event.amount or 0))
        liquid = float(state.total_liquid_balance) if state else 0
        monthly_expenses = float(state.monthly_expenses_est or 0) if state else 0

        # Rules pass: only suggest savings if > 2 months expenses covered after transfer
        if liquid < monthly_expenses * 2:
            return None

        suggested_amount = round(paycheck_amount * 0.20, 2)

        # LLM pass: enrich with explanation and refine amount
        llm_context = {
            "event": "paycheck_detected",
            "paycheck_amount": paycheck_amount,
            "liquid_balance": liquid,
            "monthly_expenses_est": monthly_expenses,
            "emergency_fund_months": float(state.emergency_fund_score or 0) if state else 0,
            "rules_suggested_amount": suggested_amount,
        }
        llm_result = await self.llm.generate_intent_explanation(llm_context)
        intents_from_llm = llm_result.get("intents", [])

        if intents_from_llm:
            llm_intent = intents_from_llm[0]
            # LLM can adjust amount but not exceed 50% of paycheck (safety cap)
            final_amount = min(
                float(llm_intent.get("amount") or suggested_amount),
                paycheck_amount * 0.50,
            )
            explanation = llm_intent.get("explanation", f"Move ${final_amount:.2f} to savings after your paycheck.")
            confidence = float(llm_intent.get("confidence", 0.80))
        else:
            final_amount = suggested_amount
            explanation = f"You received a ${paycheck_amount:.2f} paycheck. Consider moving ${final_amount:.2f} (20%) to savings."
            confidence = 0.75

        intent = Intent(
            user_id=user_id,
            triggering_event_id=event.id,
            intent_type="transfer_to_savings",
            title=f"Move ${final_amount:.2f} to savings",
            explanation=explanation,
            amount=final_amount,
            confidence_score=confidence,
            generated_by="hybrid",
            rule_ids_fired=["paycheck_v1", "savings_opportunity_v1"],
            llm_model=llm_result.get("_model"),
            llm_prompt_hash=llm_result.get("_prompt_hash"),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.INTENT_EXPIRY_HOURS),
        )
        self.db.add(intent)
        await self.db.flush()

        await self.audit.log(
            event_type="intent.created",
            user_id=user_id,
            entity_type="intent",
            entity_id=intent.id,
            actor_type="system",
            after_state={"type": intent.intent_type, "amount": final_amount, "status": intent.status},
        )
        return intent

    async def _handle_low_balance(
        self, user_id: uuid.UUID, event: FinancialEvent, state: FinancialState | None
    ) -> Intent | None:
        intent = Intent(
            user_id=user_id,
            triggering_event_id=event.id,
            intent_type="alert",
            title="Low balance warning",
            explanation=f"Your balance is running low. Current liquid balance: ${float(state.total_liquid_balance if state else 0):.2f}",
            confidence_score=0.90,
            generated_by="rules_engine",
            rule_ids_fired=["low_balance_v1"],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        self.db.add(intent)
        await self.db.flush()
        return intent

    async def _get_unprocessed_events(self, user_id: uuid.UUID) -> list[FinancialEvent]:
        result = await self.db.execute(
            select(FinancialEvent)
            .where(FinancialEvent.user_id == user_id, FinancialEvent.processed == False)
            .order_by(FinancialEvent.detected_at)
        )
        return result.scalars().all()

    async def _get_state(self, user_id: uuid.UUID) -> FinancialState | None:
        result = await self.db.execute(select(FinancialState).where(FinancialState.user_id == user_id))
        return result.scalar_one_or_none()

    async def _get_pending_intents(self, user_id: uuid.UUID) -> list[Intent]:
        result = await self.db.execute(
            select(Intent).where(Intent.user_id == user_id, Intent.status == "pending_approval")
        )
        return result.scalars().all()
