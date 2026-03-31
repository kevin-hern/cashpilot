from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid
from datetime import datetime

from app.db.database import get_db
from app.models.widget_model import Widget
from app.schemas.widget_schema import WidgetOut, WidgetCreate, WidgetUpdate
from app.services.llm_service import LLMService
from app.dependencies import get_current_user
from app.models.user_model import User

router = APIRouter()


@router.get("/data")
async def get_widget_data(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns the financial data blob injected into every widget iframe."""
    svc = LLMService(db)
    return await svc.build_widget_data(current_user.id)


@router.get("", response_model=list[WidgetOut])
async def list_widgets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Widget)
        .where(Widget.user_id == current_user.id)
        .order_by(Widget.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=WidgetOut, status_code=status.HTTP_201_CREATED)
async def create_widget(
    body: WidgetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    widget = Widget(
        user_id=current_user.id,
        title=body.title,
        description=body.description,
        component_code=body.component_code,
    )
    db.add(widget)
    await db.flush()
    return widget


@router.put("/{widget_id}", response_model=WidgetOut)
async def update_widget(
    widget_id: uuid.UUID,
    body: WidgetUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Widget).where(Widget.id == widget_id, Widget.user_id == current_user.id)
    )
    widget = result.scalar_one_or_none()
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found")
    if body.title is not None:
        widget.title = body.title
    if body.description is not None:
        widget.description = body.description
    if body.component_code is not None:
        widget.component_code = body.component_code
    widget.updated_at = datetime.utcnow()
    await db.flush()
    return widget


@router.delete("/{widget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_widget(
    widget_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Widget).where(Widget.id == widget_id, Widget.user_id == current_user.id)
    )
    widget = result.scalar_one_or_none()
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found")
    await db.delete(widget)
