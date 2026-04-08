from __future__ import annotations

from pydantic import BaseModel, Field

from value_betting_shared.models.enums import SportEnum, TierEnum


class LeagueCreateRequest(BaseModel):
    league_id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=200)
    sport: SportEnum
    country: str = Field(min_length=2, max_length=2)
    tier_required: TierEnum = TierEnum.PRO
    min_markets_per_round: int = Field(default=5, ge=1, le=50)


class LeaguePatchRequest(BaseModel):
    active: bool | None = None
    tier_required: TierEnum | None = None
    min_markets_per_round: int | None = Field(default=None, ge=1, le=50)


class MarketTypePatchRequest(BaseModel):
    enabled: bool | None = None
    min_bookmaker_coverage_pct: int | None = Field(default=None, ge=0, le=100)


class PollingConfigPatchRequest(BaseModel):
    polling_interval_24h_sec: int | None = Field(default=None, ge=15, le=300)
    polling_interval_72h_sec: int | None = Field(default=None, ge=60, le=1800)
    polling_interval_beyond_72h_sec: int | None = Field(default=None, ge=300, le=3600)


class PollingOverrideCreateRequest(BaseModel):
    league_id: str = Field(pattern=r"^[a-z0-9_]+$")
    bookmaker_id: str = Field(pattern=r"^[a-z0-9_]+$")
    interval_seconds: int = Field(ge=15, le=300)


class DegradationActivateRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
