"""
Deterministic rules engine. Evaluates transactions against rule definitions
and emits FinancialEvents. Fast, auditable, no LLM involved.
"""
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
import uuid

from app.models.transaction_model import Transaction, FinancialEvent, FinancialState


PAYROLL_KEYWORDS = {
    "adp", "gusto", "paychex", "workday payroll", "direct deposit",
    "payroll", "wages", "salary", "intuit payroll",
}


@dataclass
class RuleResult:
    fired: bool
    event_type: str
    confidence: float
    metadata: dict = field(default_factory=dict)
    rule_id: str = ""


class RulesEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def evaluate_transaction(
        self, txn: Transaction, state: FinancialState | None
    ) -> list[RuleResult]:
        results = []
        results.extend(self._paycheck_rules(txn, state))
        results.extend(self._large_deposit_rules(txn))
        results.extend(self._large_expense_rules(txn))
        if state:
            results.extend(self._low_balance_rules(txn, state))
        return [r for r in results if r.fired]

    def _paycheck_rules(self, txn: Transaction, state: FinancialState | None) -> list[RuleResult]:
        # Income: Plaid uses positive amount for debits; income is negative amount
        if txn.amount >= 0:
            return []

        income_amount = abs(txn.amount)
        if income_amount < 200:
            return []

        keyword_match = any(kw in (txn.merchant_name or "").lower() or kw in (txn.raw_name or "").lower()
                            for kw in PAYROLL_KEYWORDS)
        category_match = txn.category_primary in ("INCOME", "TRANSFER_IN")

        if not (keyword_match or category_match):
            return []

        confidence = 0.70
        if keyword_match:
            confidence += 0.15
        if category_match:
            confidence += 0.10
        if state and state.pay_frequency:
            confidence = min(confidence + 0.05, 0.99)

        return [RuleResult(
            fired=True,
            event_type="paycheck",
            confidence=round(confidence, 3),
            rule_id="paycheck_v1",
            metadata={"amount": income_amount, "merchant": txn.merchant_name},
        )]

    def _large_deposit_rules(self, txn: Transaction) -> list[RuleResult]:
        if txn.amount < -500:  # income > $500
            return [RuleResult(
                fired=True,
                event_type="large_deposit",
                confidence=0.95,
                rule_id="large_deposit_v1",
                metadata={"amount": abs(txn.amount)},
            )]
        return []

    def _large_expense_rules(self, txn: Transaction) -> list[RuleResult]:
        if txn.amount > 500:
            return [RuleResult(
                fired=True,
                event_type="large_expense",
                confidence=0.95,
                rule_id="large_expense_v1",
                metadata={"amount": txn.amount, "merchant": txn.merchant_name},
            )]
        return []

    def _low_balance_rules(self, txn: Transaction, state: FinancialState) -> list[RuleResult]:
        if state.monthly_expenses_est and state.total_liquid_balance < state.monthly_expenses_est:
            return [RuleResult(
                fired=True,
                event_type="low_balance",
                confidence=0.90,
                rule_id="low_balance_v1",
                metadata={
                    "balance": float(state.total_liquid_balance),
                    "monthly_expenses": float(state.monthly_expenses_est),
                },
            )]
        return []

    async def emit_events(
        self, user_id: uuid.UUID, txn: Transaction, results: list[RuleResult]
    ) -> list[FinancialEvent]:
        events = []
        for result in results:
            event = FinancialEvent(
                user_id=user_id,
                event_type=result.event_type,
                transaction_id=txn.id,
                account_id=txn.account_id,
                amount=txn.amount,
                metadata_={
                    "confidence": result.confidence,
                    "rule_id": result.rule_id,
                    **result.metadata,
                },
            )
            self.db.add(event)
            events.append(event)
        await self.db.flush()
        return events
