from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
import uuid

from app.db.database import get_db
from app.services.llm_service import LLMService
from app.dependencies import get_current_user
from app.models.user_model import User

router = APIRouter()


class MessageRequest(BaseModel):
    content: str


class SessionResponse(BaseModel):
    id: uuid.UUID
    title: str | None


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = LLMService(db)
    session = await svc.create_session(current_user.id)
    return SessionResponse(id=session.id, title=session.title)


@router.get("/sessions")
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = LLMService(db)
    return await svc.list_sessions(current_user.id)


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID,
    body: MessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a chat message. Returns SSE stream of assistant response."""
    svc = LLMService(db)
    session = await svc.get_session(current_user.id, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return StreamingResponse(
        svc.stream_response(current_user, session, body.content),
        media_type="text/event-stream",
    )


@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = LLMService(db)
    return await svc.get_messages(current_user.id, session_id)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = LLMService(db)
    await svc.delete_session(current_user.id, session_id)
