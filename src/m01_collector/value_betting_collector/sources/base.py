from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from value_betting_shared.models.enums import MarketTypeEnum, OddsSourceEnum


@dataclass
class RawOddsData:
    event_id: str
    sport: str
    league_id: str
    home_team: str
    away_team: str
    commence_time: str
    bookmaker_id: str
    market_type: MarketTypeEnum
    odds_home: float
    odds_draw: float | None
    odds_away: float
    source: OddsSourceEnum
    is_pinnacle: bool = False


@dataclass
class BetfairEnrichment:
    event_id: str
    matched_amount: float | None = None
    back_available_home: float | None = None
    back_available_draw: float | None = None
    back_available_away: float | None = None


@dataclass
class MatchContext:
    event_id: str
    status: str | None = None
    venue: str | None = None
    round: str | None = None


@dataclass
class FetchResult:
    odds: list[RawOddsData] = field(default_factory=list)
    requests_used: int = 0
    errors: list[str] = field(default_factory=list)


@runtime_checkable
class OddsSource(Protocol):
    async def fetch_odds(
        self,
        sport: str,
        league_ids: list[str],
        market_types: list[MarketTypeEnum],
    ) -> FetchResult: ...


@runtime_checkable
class ExchangeSource(Protocol):
    async def fetch_exchange_data(
        self,
        event_ids: list[str],
    ) -> list[BetfairEnrichment]: ...


@runtime_checkable
class MatchDataSource(Protocol):
    async def fetch_match_context(
        self,
        event_ids: list[str],
    ) -> list[MatchContext]: ...
