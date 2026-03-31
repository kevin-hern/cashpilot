from pydantic import BaseModel
import uuid
from datetime import datetime


class WidgetOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    component_code: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WidgetCreate(BaseModel):
    title: str
    description: str | None = None
    component_code: str


class WidgetUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    component_code: str | None = None
