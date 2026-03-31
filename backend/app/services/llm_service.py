"""
LLM service — wraps the Anthropic Claude API.
Used by the decision engine for reasoning, and directly for the chat interface.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import AsyncGenerator
import anthropic
import asyncio
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

WIDGET_STREAM_ADDON = """
The user is asking you to build a custom dashboard widget. Acknowledge that you're generating it (1-2 sentences max). Be specific about what it will visualize based on their request. Say "I'm building" since the widget is being generated now. Do NOT generate any code or HTML — just describe what you're making.
"""

WIDGET_SYSTEM_PROMPT = """You are a financial dashboard widget generator for CashPilot.

Generate a self-contained HTML widget based on the user's request. The widget will run in a sandboxed iframe on a financial dashboard.

## Data Available
Financial data is injected as `window.CASHPILOT_DATA` before your script runs, with this structure:
{
  "accounts": [{"name": string, "type": string, "subtype": string, "current_balance": number, "available_balance": number}],
  "liquid_balance": number | null,
  "monthly_income": number | null,
  "monthly_expenses": number | null,
  "monthly_cash_flow": number | null,
  "transactions": [{"date": "YYYY-MM-DD", "amount": number, "name": string, "category": string}],
  "paychecks": [{"amount": number, "source": string}]
}
Note: transaction `amount` is positive = expense (money out), negative = income (money in).

## Output Format
Return ONLY a raw JSON object — no markdown, no code blocks, no explanation, no backticks:
{"title": "Widget Title Here", "html": "<!DOCTYPE html>...complete HTML here..."}

## HTML Requirements
- Complete document starting with `<!DOCTYPE html>`
- Load Chart.js ONLY from: `https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js`
- All CSS must be inline in a `<style>` tag in `<head>`
- `window.CASHPILOT_DATA` is guaranteed to exist when your DOMContentLoaded script runs
- Always handle null/missing data gracefully (use defaults like 0)
- Escape any forward slashes in the HTML when embedding in JSON (use \\/ instead of /)

## Design System
- Body/page background: #09090b
- Card background: #18181b
- Border color: #27272a
- Primary text: #fafafa
- Muted text: #a1a1aa
- Blue accent: #3b82f6
- Green: #10b981 (positive, income)
- Red: #ef4444 (negative, expenses)
- Yellow: #f59e0b (warnings)
- Font: system-ui, -apple-system, sans-serif
- Base font size: 13px, label size: 11px
- Card padding: 16px, border-radius: 12px
- Design for exactly 370px height, 100% width
- No scrollbars — everything must fit in 370px

## Required Script Boilerplate
Always start your script block with:
  Chart.defaults.color = '#a1a1aa';
  Chart.defaults.borderColor = '#27272a';
  Chart.defaults.font.family = "system-ui, -apple-system, sans-serif";
  Chart.defaults.font.size = 11;
  const fmtCurrency = n => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(n??0);
  const fmtDate = d => new Date(d+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'});

Always wrap in:
  document.addEventListener('DOMContentLoaded', () => { const data = window.CASHPILOT_DATA || {}; ... });
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
                sign = "-" if txn.amount > 0 else "+"
                amount = abs(float(txn.amount))
                name = txn.merchant_name or txn.raw_name or "Unknown"
                category = txn.category_primary or "uncategorized"
                lines.append(f"- {txn.posted_at} | {sign}${amount:,.2f} | {name} | {category}")
        else:
            lines.append("- No transactions in the last 30 days.")

        return "\n".join(lines)

    async def build_widget_data(self, user_id: uuid.UUID) -> dict:
        """Build the structured JSON blob injected into every widget iframe as window.CASHPILOT_DATA."""
        from datetime import datetime, timedelta, timezone
        from app.models.paycheck_model import Paycheck

        acct_result = await self.db.execute(select(Account).where(Account.user_id == user_id))
        accounts_out = []
        for acct in acct_result.scalars().all():
            bal_result = await self.db.execute(
                select(AccountBalance)
                .where(AccountBalance.account_id == acct.id)
                .order_by(AccountBalance.snapshot_at.desc())
                .limit(1)
            )
            bal = bal_result.scalar_one_or_none()
            accounts_out.append({
                "name": acct.official_name or acct.name,
                "type": acct.type,
                "subtype": acct.subtype,
                "current_balance": float(bal.current) if bal and bal.current is not None else None,
                "available_balance": float(bal.available) if bal and bal.available is not None else None,
            })

        state_result = await self.db.execute(
            select(FinancialState).where(FinancialState.user_id == user_id)
        )
        state = state_result.scalar_one_or_none()
        monthly_income = float(state.monthly_income_est) if state and state.monthly_income_est else None
        monthly_expenses = float(state.monthly_expenses_est) if state and state.monthly_expenses_est else None
        liquid_balance = float(state.total_liquid_balance) if state and state.total_liquid_balance else None

        cutoff = datetime.now(timezone.utc).date() - timedelta(days=90)
        txn_result = await self.db.execute(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.pending == False,
                Transaction.posted_at >= cutoff,
            ).order_by(Transaction.posted_at.desc()).limit(300)
        )
        transactions_out = [
            {
                "date": str(t.posted_at),
                "amount": float(t.amount),
                "name": t.merchant_name or t.raw_name or "Unknown",
                "category": t.category_primary or "OTHER",
            }
            for t in txn_result.scalars().all()
        ]

        pc_result = await self.db.execute(
            select(Paycheck)
            .where(Paycheck.user_id == user_id)
            .order_by(Paycheck.created_at.desc())
            .limit(12)
        )
        paychecks_out = [
            {"amount": float(p.amount), "source": p.source}
            for p in pc_result.scalars().all()
        ]

        return {
            "accounts": accounts_out,
            "liquid_balance": liquid_balance,
            "monthly_income": monthly_income,
            "monthly_expenses": monthly_expenses,
            "monthly_cash_flow": (
                round(monthly_income - monthly_expenses, 2)
                if monthly_income is not None and monthly_expenses is not None
                else None
            ),
            "transactions": transactions_out,
            "paychecks": paychecks_out,
        }

    # ── Widget generation ─────────────────────────────────────────────────────

    def _is_widget_request(self, content: str) -> bool:
        lower = content.lower()
        if "widget" in lower:
            return True
        chart_words = {"chart", "graph", "visualization", "visualize", "plot"}
        action_words = {"build", "create", "make", "show me", "add", "generate"}
        return any(c in lower for c in chart_words) and any(a in lower for a in action_words)

    def _generate_widget_code_sync(self, user_content: str) -> tuple[str, str] | None:
        """Synchronous Anthropic call — always run via asyncio.to_thread. Returns (title, html) or None."""
        try:
            response = self.client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=4096,
                system=WIDGET_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"Build a financial dashboard widget for: {user_content}",
                }],
            )
            raw = response.content[0].text.strip()

            # Strip markdown code fences if present
            if "```" in raw:
                parts = raw.split("```")
                for part in parts:
                    candidate = part.strip()
                    if candidate.startswith("json"):
                        candidate = candidate[4:].strip()
                    try:
                        json.loads(candidate)
                        raw = candidate
                        break
                    except Exception:
                        continue

            data = json.loads(raw)
            title = str(data.get("title", "My Widget"))[:200]
            html = data.get("html", "")
            return (title, html) if html else None
        except Exception:
            return None

    # ── Core streaming ────────────────────────────────────────────────────────

    async def stream_response(
        self, user: User, session: ChatSession, user_content: str
    ) -> AsyncGenerator[str, None]:
        is_widget = self._is_widget_request(user_content)

        # Persist user message
        user_msg = ChatMessage(session_id=session.id, role="user", content=user_content)
        self.db.add(user_msg)
        await self.db.flush()

        # Build message history (last 20 messages)
        history = await self.get_messages(user.id, session.id)
        messages = [{"role": m.role, "content": m.content} for m in history[-20:] if m.role != "system"]

        # Build system prompt
        financial_context = await self._build_financial_context(user.id)
        system_prompt = f"{BASE_SYSTEM_PROMPT}\n{financial_context}"
        if is_widget:
            system_prompt += f"\n{WIDGET_STREAM_ADDON}"

        # Stream Claude text response first
        full_response = ""
        try:
            with self.client.messages.stream(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=512 if is_widget else 1024,
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

        # Persist assistant text message
        assistant_msg = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=full_response,
        )
        self.db.add(assistant_msg)
        await self.db.flush()

        # After text stream: generate widget (async thread so we don't block event loop)
        if is_widget:
            try:
                result = await asyncio.to_thread(self._generate_widget_code_sync, user_content)
                if result:
                    from app.models.widget_model import Widget
                    title, code = result
                    widget = Widget(user_id=user.id, title=title, component_code=code)
                    self.db.add(widget)
                    await self.db.flush()
                    yield f"data: {json.dumps({'type': 'widget', 'id': str(widget.id), 'title': title, 'code': code})}\n\n"
            except Exception:
                pass  # Non-fatal — text response already delivered

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
