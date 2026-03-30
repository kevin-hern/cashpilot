"""
LLM service — wraps the Anthropic Claude API.
Used by the decision engine for reasoning, and directly for the chat interface.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import AsyncGenerator
import anthropic
import json
import hashlib
import uuid

from app.core.config import settings
from app.models.chat_model import ChatSession, ChatMessage
from app.models.user_model import User
from app.models.plaid_model import Account, AccountBalance
from app.models.transaction_model import Transaction, FinancialState


BASE_SYSTEM_PROMPT = """You are CashPilot, an AI financial assistant. You help users understand their spending, detect income patterns, and make smart financial decisions.

Your role:
- Analyze financial data provided in context
- Explain financial patterns in plain English
- Suggest concrete, actionable financial moves
- NEVER execute transactions yourself — always surface recommendations for the user to approve
- Be concise, specific, and avoid jargon

When generating financial recommendations, always output them in this JSON structure inside <intent> tags:
<intent>
{
  "type": "transfer_to_savings|pay_bill|invest|alert|suggestion",
  "title": "Short action title",
  "explanation": "Plain English explanation",
  "amount": null or number,
  "confidence": 0.0-1.0
}
</intent>
"""


class LLMService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def create_session(self, user_id: uuid.UUID) -> ChatSession:
        session = ChatSession(user_id=user_id)
        self.db.add(session)
        await self.db.flush()
        return session

    async def list_sessions(self, user_id: uuid.UUID) -> list[ChatSession]:
        result = await self.db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(50)
        )
        return result.scalars().all()

    async def get_session(self, user_id: uuid.UUID, session_id: uuid.UUID) -> ChatSession | None:
        result = await self.db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_messages(self, user_id: uuid.UUID, session_id: uuid.UUID) -> list[ChatMessage]:
        session = await self.get_session(user_id, session_id)
        if not session:
            return []
        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        return result.scalars().all()

    async def delete_session(self, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        session = await self.get_session(user_id, session_id)
        if session:
            await self.db.delete(session)

    async def _build_financial_context(self, user_id: uuid.UUID) -> str:
        from datetime import datetime, timedelta, timezone

        lines: list[str] = ["## User Financial Context\n"]

        # ── Accounts & balances ───────────────────────────────────────────────
        acct_result = await self.db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        accounts = acct_result.scalars().all()

        if accounts:
            lines.append("### Accounts")
            for acct in accounts:
                bal_result = await self.db.execute(
                    select(AccountBalance)
                    .where(AccountBalance.account_id == acct.id)
                    .order_by(AccountBalance.snapshot_at.desc())
                    .limit(1)
                )
                bal = bal_result.scalar_one_or_none()
                current = f"${float(bal.current):,.2f}" if bal else "unknown"
                available = (
                    f" (${float(bal.available):,.2f} available)" if bal and bal.available is not None else ""
                )
                label = acct.official_name or acct.name
                lines.append(f"- {label} [{acct.type}/{acct.subtype or '—'}]: {current}{available}")
        else:
            lines.append("### Accounts\n- No accounts linked.")

        # ── Financial state ───────────────────────────────────────────────────
        state_result = await self.db.execute(
            select(FinancialState).where(FinancialState.user_id == user_id)
        )
        state = state_result.scalar_one_or_none()

        lines.append("\n### Financial Summary")
        if state:
            def fmt(v): return f"${float(v):,.2f}" if v is not None else "unknown"
            lines.append(f"- Total liquid balance: {fmt(state.total_liquid_balance)}")
            lines.append(f"- Est. monthly income: {fmt(state.monthly_income_est)}")
            lines.append(f"- Est. monthly expenses: {fmt(state.monthly_expenses_est)}")
            if state.monthly_income_est and state.monthly_expenses_est:
                cash_flow = float(state.monthly_income_est) - float(state.monthly_expenses_est)
                lines.append(f"- Monthly cash flow: ${cash_flow:,.2f}")
            if state.emergency_fund_score is not None:
                lines.append(f"- Emergency fund coverage: {float(state.emergency_fund_score):.1f} months")
            if state.pay_frequency:
                lines.append(f"- Pay frequency: {state.pay_frequency}")
        else:
            lines.append("- No financial summary available yet (sync transactions first).")

        # ── Recent transactions (last 30 days) ────────────────────────────────
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
        txn_result = await self.db.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id, Transaction.posted_at >= cutoff)
            .order_by(Transaction.posted_at.desc())
            .limit(50)
        )
        transactions = txn_result.scalars().all()

        lines.append("\n### Recent Transactions (last 30 days)")
        if transactions:
            for txn in transactions:
                sign = "-" if txn.amount > 0 else "+"  # Plaid: positive = debit
                amount = abs(float(txn.amount))
                name = txn.merchant_name or txn.raw_name or "Unknown"
                category = txn.category_primary or "uncategorized"
                lines.append(f"- {txn.posted_at} | {sign}${amount:,.2f} | {name} | {category}")
        else:
            lines.append("- No transactions in the last 30 days.")

        return "\n".join(lines)

    async def stream_response(
        self, user: User, session: ChatSession, user_content: str
    ) -> AsyncGenerator[str, None]:
        # Persist user message
        user_msg = ChatMessage(session_id=session.id, role="user", content=user_content)
        self.db.add(user_msg)
        await self.db.flush()

        # Build message history (last 20 messages for context)
        history = await self.get_messages(user.id, session.id)
        messages = [{"role": m.role, "content": m.content} for m in history[-20:] if m.role != "system"]

        # Inject financial context into system prompt
        financial_context = await self._build_financial_context(user.id)
        system_prompt = f"{BASE_SYSTEM_PROMPT}\n{financial_context}"

        full_response = ""
        try:
            with self.client.messages.stream(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield f"data: {json.dumps({'delta': text})}\n\n"
        except Exception as e:
            error_msg = f"I'm sorry, I couldn't process your request right now. ({type(e).__name__})"
            yield f"data: {json.dumps({'delta': error_msg})}\n\n"
            full_response = error_msg

        # Persist assistant message
        assistant_msg = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=full_response,
        )
        self.db.add(assistant_msg)
        await self.db.flush()
        yield "data: [DONE]\n\n"

    async def generate_intent_explanation(self, context: dict) -> dict:
        """Used by the decision engine to reason about financial events."""
        prompt = f"""Given this financial context, analyze and return a JSON intent object:

Context: {json.dumps(context, indent=2)}

Return ONLY valid JSON with this shape:
{{
  "intents": [{{
    "type": "transfer_to_savings|pay_bill|invest|alert|suggestion",
    "title": "...",
    "explanation": "...",
    "amount": null or number,
    "confidence": 0.0-1.0,
    "risk_flags": []
  }}]
}}"""

        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        response = self.client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {"intents": []}

        return {**result, "_prompt_hash": prompt_hash, "_model": settings.ANTHROPIC_MODEL}
