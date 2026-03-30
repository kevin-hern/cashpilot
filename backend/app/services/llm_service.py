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


SYSTEM_PROMPT = """You are CashPilot, an AI financial assistant. You help users understand their spending, detect income patterns, and make smart financial decisions.

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

        full_response = ""
        with self.client.messages.stream(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                full_response += text
                yield f"data: {json.dumps({'delta': text})}\n\n"

        # Persist assistant message
        assistant_msg = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=full_response,
            token_count=stream.get_final_usage().output_tokens if hasattr(stream, "get_final_usage") else None,
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
