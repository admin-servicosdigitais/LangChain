from __future__ import annotations

import logging

import httpx

from value_betting_collector.sources.base import MatchContext

logger = logging.getLogger(__name__)


class ApiFootballClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://v3.football.api-sports.io",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def fetch_match_context(
        self,
        event_ids: list[str],
    ) -> list[MatchContext]:
        results: list[MatchContext] = []
        for event_id in event_ids:
            try:
                ctx = await self._fetch_single(event_id)
                if ctx:
                    results.append(ctx)
            except Exception:
                logger.warning(
                    "API-Football fetch failed for %s, skipping",
                    event_id,
                    exc_info=True,
                )
        return results

    async def _fetch_single(self, event_id: str) -> MatchContext | None:
        response = await self._client.get(
            f"{self._base_url}/fixtures",
            params={"id": event_id},
            headers={"x-apisports-key": self._api_key},
        )
        response.raise_for_status()
        data = response.json()

        fixtures = data.get("response", [])
        if not fixtures:
            return None

        fixture = fixtures[0]
        fixture_info = fixture.get("fixture", {})
        venue_data = fixture_info.get("venue", {})
        league_data = fixture.get("league", {})

        status_short = fixture_info.get("status", {}).get("short", "")
        status_map = {
            "NS": "scheduled",
            "1H": "live",
            "HT": "live",
            "2H": "live",
            "ET": "live",
            "FT": "finished",
            "AET": "finished",
            "PEN": "finished",
            "PST": "postponed",
            "CANC": "cancelled",
        }

        return MatchContext(
            event_id=event_id,
            status=status_map.get(status_short, "scheduled"),
            venue=venue_data.get("name"),
            round=league_data.get("round"),
        )

    async def close(self) -> None:
        await self._client.aclose()
