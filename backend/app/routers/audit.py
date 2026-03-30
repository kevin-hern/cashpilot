from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from pydantic import BaseModel
import uuid

from app.db.database import get_db
from app.services.audit_service import AuditService
from app.dependencies import get_current_user
from app.models.user_model import User

router = APIRouter()


class AuditLogOut(BaseModel):
    id: int
    actor_type: str
    event_type: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    after_state: dict | None
    request_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[AuditLogOut])
async def list_audit_log(
    entity_type: str | None = Query(None),
    entity_id: uuid.UUID | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read-only view of the audit log for the current user's entities."""
    svc = AuditService(db)
    return await svc.list_for_user(
        current_user.id,
        entity_type=entity_type,
        entity_id=entity_id,
        start=start,
        end=end,
        limit=limit,
    )
