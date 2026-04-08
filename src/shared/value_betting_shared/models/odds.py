from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field, model_validator

from value_betting_shared.models.enums import (
    MarketTypeEnum,
    MatchStatusEnum,
    OddsSourceEnum,
)

_TTL_MONTHS = 13


class PinnacleOdds(BaseModel):
    home: float = Field(gt=1.0)
    draw: float | None = Field(default=None, gt=1.0)
    away: float = Field(gt=1.0)


class ExchangeBackAvailable(BaseModel):
    home: float = Field(ge=0)
    draw: float | None = Field(default=None, ge=0)
    away: float = Field(ge=0)


class OddsSnapshot(BaseModel):
    event_id: str
    event_canonical_id: str | None = None
    market_type: MarketTypeEnum
    bookmaker_id: str
    odds_home: float = Field(gt=1.0)
    odds_draw: float | None = Field(default=None, gt=1.0)
    odds_away: float = Field(gt=1.0)
    pinnacle_odds: PinnacleOdds | None = None
    pinnacle_margin: float | None = Field(default=None, ge=0, le=0.15)
    no_sharp_reference: bool = False
    correction_of: str | None = None
    collected_at: datetime
    source: OddsSourceEnum
    high_volatility: bool = False
    betfair_matched_amount: float | None = None
    betfair_available_to_back: ExchangeBackAvailable | None = None
    exchange_volume_usd: float | None = None
    exchange_back_available: ExchangeBackAvailable | None = None
    low_liquidity: bool = False
    match_status: MatchStatusEnum | None = None
    match_venue: str | None = None
    match_round: str | None = None
    expires_at: int = 0

    @model_validator(mode="after")
    def _validate_pinnacle_and_ttl(self) -> OddsSnapshot:
        if not self.no_sharp_reference and self.pinnacle_odds is None:
            raise ValueError(
                "pinnacle_odds é obrigatório quando no_sharp_reference=False"
            )
        if self.expires_at == 0:
            ttl_dt = self.collected_at + timedelta(days=_TTL_MONTHS * 30)
            self.expires_at = int(ttl_dt.timestamp())
        return self

    @property
    def sort_key(self) -> str:
        ts = self.collected_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        return f"{ts}#{self.source.value}"

    def to_dynamodb_item(self) -> dict[str, str | float | int | bool | None]:
        return {
            "event_id": self.event_id,
            "sort_key": self.sort_key,
            "event_canonical_id": self.event_canonical_id,
            "market_type": self.market_type.value,
            "bookmaker_id": self.bookmaker_id,
            "odds_home": self.odds_home,
            "odds_draw": self.odds_draw,
            "odds_away": self.odds_away,
            "pinnacle_odds": self.pinnacle_odds.model_dump() if self.pinnacle_odds else None,
            "pinnacle_margin": self.pinnacle_margin,
            "no_sharp_reference": self.no_sharp_reference,
            "correction_of": self.correction_of,
            "collected_at": self.collected_at.isoformat(),
            "source": self.source.value,
            "high_volatility": self.high_volatility,
            "betfair_matched_amount": self.betfair_matched_amount,
            "exchange_volume_usd": self.exchange_volume_usd,
            "low_liquidity": self.low_liquidity,
            "match_status": self.match_status.value if self.match_status else None,
            "match_venue": self.match_venue,
            "match_round": self.match_round,
            "expires_at": self.expires_at,
        }


class OddsMovementEvent(BaseModel):
    event_id: str
    event_canonical_id: str | None = None
    market_type: MarketTypeEnum
    bookmaker_id: str
    previous_odds: PinnacleOdds
    current_odds: PinnacleOdds
    delta_pct: float
    series_last_5_snapshots: list[dict[str, float | str | None]] = Field(default_factory=list)
    exchange_volume_delta: float | None = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
