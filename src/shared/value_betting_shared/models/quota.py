from __future__ import annotations

from pydantic import BaseModel, Field

from value_betting_shared.models.enums import AlertLevelEnum, QuotaRecommendationEnum


class QuotaUsage(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    requests_count: int = 0
    requests_limit: int
    percentage_consumed: float = Field(ge=0)
    alert_level: AlertLevelEnum | None = None


class QuotaProjection(BaseModel):
    current_month: str = Field(pattern=r"^\d{4}-\d{2}$")
    projected_requests: int
    projected_percentage: float
    projected_exhaustion_date: str | None = None
    recommendation: QuotaRecommendationEnum | None = None
