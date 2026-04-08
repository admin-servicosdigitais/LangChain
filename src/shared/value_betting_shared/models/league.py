from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from value_betting_shared.models.enums import SportEnum, TierEnum


class League(BaseModel):
    league_id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    sport: SportEnum
    country: str = Field(min_length=2, max_length=2)
    active: bool = True
    tier_required: TierEnum = TierEnum.PRO
    min_markets_per_round: int = Field(default=5, ge=1, le=50)
    last_collection_at: datetime | None = None
    markets_collected_24h: int = 0
    estimated_quota_cost: float | None = None


class PollingConfig(BaseModel):
    polling_interval_24h_sec: int = Field(default=30, ge=15, le=300)
    polling_interval_72h_sec: int = Field(default=300, ge=60, le=1800)
    polling_interval_beyond_72h_sec: int = Field(default=1800, ge=300, le=3600)


class PollingOverride(BaseModel):
    league_id: str = Field(pattern=r"^[a-z0-9_]+$")
    bookmaker_id: str = Field(pattern=r"^[a-z0-9_]+$")
    interval_seconds: int = Field(ge=15, le=300)
    created_at: datetime | None = None
    created_by: str | None = None


class BookmakerReliability(BaseModel):
    bookmaker_id: str
    name: str
    unreliable: bool = False
    unreliable_since: datetime | None = None
    coverage_pct_7d: float = Field(ge=0, le=100)
