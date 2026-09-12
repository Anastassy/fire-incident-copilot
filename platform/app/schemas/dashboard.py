from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class DashboardCreate(BaseModel):
    """Custom dashboard assembled by an agent on operator request, or a default view."""

    title: str
    created_by: Literal["agent", "operator", "default"] = "agent"
    spec: dict


class DashboardUpdate(BaseModel):
    title: Optional[str] = None
    spec: Optional[dict] = None


class DashboardOut(BaseModel):
    id: str
    title: str
    created_by: str
    spec: dict
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
