from __future__ import annotations

import asyncio
import logging

import httpx
from value_betting_shared.models.enums import MarketTypeEnum, OddsSourceEnum

from value_betting_collector.sources.base import FetchResult, RawOddsData

logger = logging.getLogger(__name__)

_MARKET_MAP: dict[MarketTypeEnum, str] = {
    MarketTypeEnum.ONE_X_TWO: "h2h",
    MarketTypeEnum.OVER_UNDER_2_5: "totals",
    MarketTypeEnum.OVER_UNDER_3_5: "totals",
    MarketTypeEnum.ASIAN_HANDICAP: "spreads",
    MarketTypeEnum.BTTS: "h2h",
}

_BACKOFF_DELAYS = [1, 2, 4, 8]
_PINNACLE_KEY = "pinnacle"


class TheOddsApiClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.the-odds-api.com/v4",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client = client or httpx.AsyncClient(timeout=15.0)
        self._requests_used = 0

    @property
    def requests_used(self) -> int:
        return self._requests_used

    async def fetch_odds(
        self,
        sport: str,
        league_ids: list[str],
        market_types: list[MarketTypeEnum],
    ) -> FetchResult:
        all_odds: list[RawOddsData] = []
        errors: list[str] = []
        requests_count = 0

        markets_param = ",".join(
            {_MARKET_MAP[mt] for mt in market_types if mt in _MARKET_MAP}
        )

        for attempt in range(len(_BACKOFF_DELAYS) + 1):
            try:
                response = await self._client.get(
                    f"{self._base_url}/sports/{sport}/odds",
                    params={
                        "apiKey": self._api_key,
                        "regions": "eu",
                        "markets": markets_param,
                        "oddsFormat": "decimal",
                    },
                )
                requests_count += 1
                self._requests_used += 1

                if response.status_code == 429:
                    if attempt < len(_BACKOFF_DELAYS):
                        delay = _BACKOFF_DELAYS[attempt]
                        logger.warning("Rate limited, backoff %ds", delay)
                        await asyncio.sleep(delay)
                        continue
                    errors.append("Rate limit exceeded after max retries")
                    break

                response.raise_for_status()
                events = response.json()

                for event in events:
                    event_id = event.get("id", "")
                    home_team = event.get("home_team", "")
                    away_team = event.get("away_team", "")
                    commence = event.get("commence_time", "")
                    sport_key = event.get("sport_key", sport)

                    for bookmaker in event.get("bookmakers", []):
                        bk_key = bookmaker.get("key", "")
                        for market in bookmaker.get("markets", []):
                            parsed = self._parse_market(
                                event_id=event_id,
                                sport=sport_key,
                                league_id=sport_key,
                                home_team=home_team,
                                away_team=away_team,
                                commence_time=commence,
                                bookmaker_id=bk_key,
                                market_data=market,
                            )
                            if parsed:
                                all_odds.extend(parsed)
                break

            except httpx.HTTPStatusError as e:
                errors.append(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
                break
            except httpx.RequestError as e:
                errors.append(f"Request error: {e}")
                if attempt < len(_BACKOFF_DELAYS):
                    await asyncio.sleep(_BACKOFF_DELAYS[attempt])
                    continue
                break

        return FetchResult(odds=all_odds, requests_used=requests_count, errors=errors)

    def _parse_market(
        self,
        event_id: str,
        sport: str,
        league_id: str,
        home_team: str,
        away_team: str,
        commence_time: str,
        bookmaker_id: str,
        market_data: dict,
    ) -> list[RawOddsData]:
        market_key = market_data.get("key", "")
        outcomes = market_data.get("outcomes", [])
        results: list[RawOddsData] = []

        if market_key == "h2h" and len(outcomes) >= 2:
            odds_map: dict[str, float] = {}
            for o in outcomes:
                name = o.get("name", "")
                price = o.get("price", 0.0)
                if name == home_team:
                    odds_map["home"] = price
                elif name == away_team:
                    odds_map["away"] = price
                elif name == "Draw":
                    odds_map["draw"] = price

            if "home" in odds_map and "away" in odds_map:
                results.append(
                    RawOddsData(
                        event_id=event_id,
                        sport=sport,
                        league_id=league_id,
                        home_team=home_team,
                        away_team=away_team,
                        commence_time=commence_time,
                        bookmaker_id=bookmaker_id,
                        market_type=MarketTypeEnum.ONE_X_TWO,
                        odds_home=odds_map["home"],
                        odds_draw=odds_map.get("draw"),
                        odds_away=odds_map["away"],
                        source=OddsSourceEnum.THE_ODDS_API,
                        is_pinnacle=(bookmaker_id == _PINNACLE_KEY),
                    )
                )

        elif market_key == "totals":
            for o in outcomes:
                point = o.get("point")
                if point == 2.5:
                    results.append(
                        RawOddsData(
                            event_id=event_id,
                            sport=sport,
                            league_id=league_id,
                            home_team=home_team,
                            away_team=away_team,
                            commence_time=commence_time,
                            bookmaker_id=bookmaker_id,
                            market_type=MarketTypeEnum.OVER_UNDER_2_5,
                            odds_home=o.get("price", 0.0),
                            odds_draw=None,
                            odds_away=0.0,
                            source=OddsSourceEnum.THE_ODDS_API,
                            is_pinnacle=(bookmaker_id == _PINNACLE_KEY),
                        )
                    )

        return results

    async def close(self) -> None:
        await self._client.aclose()
