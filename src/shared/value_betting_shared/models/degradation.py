from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DegradationStatus(BaseModel):
    active: bool = False
    activated_at: datetime | None = None
    activated_by: str | None = None
    reason: str | None = None
    auto_activated: bool = False
    affected_leagues: list[str] = Field(default_factory=list)
