from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.intent_schema import IntentOut
from app.services.decision_engine import DecisionEngine
from app.dependencies import get_current_user
from app.models.user_model import User

router = APIRouter()


@router.get("/", response_model=list[IntentOut])
async def list_intents(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List AI-generated intents for the current user."""
    engine = DecisionEngine(db)
    return await engine.list_intents(current_user.id, status=status, limit=limit)


@router.post("/run", status_code=202)
async def trigger_decision_run(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger the decision engine for the current user (dev/debug)."""
    engine = DecisionEngine(db)
    await engine.run_for_user(current_user.id)
    return {"message": "Decision engine run enqueued"}
