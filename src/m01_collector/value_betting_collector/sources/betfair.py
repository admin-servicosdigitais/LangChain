from __future__ import annotations

import asyncio
import logging

import httpx

from value_betting_collector.sources.base import BetfairEnrichment

logger = logging.getLogger(__name__)


class BetfairClient:
    def __init__(
        self,
        app_key: str,
        session_token: str,
        base_url: str = "https://api.betfair.com/exchange",
        max_rps: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._app_key = app_key
        self._session_token = session_token
        self._base_url = base_url
        self._max_rps = max_rps
        self._semaphore = asyncio.Semaphore(max_rps)
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def fetch_exchange_data(
        self,
        event_ids: list[str],
    ) -> list[BetfairEnrichment]:
        results: list[BetfairEnrichment] = []
        for event_id in event_ids:
            try:
                enrichment = await self._fetch_single(event_id)
                if enrichment:
                    results.append(enrichment)
            except Exception:
                logger.warning(
                    "Betfair fetch failed for event %s, skipping",
                    event_id,
                    exc_info=True,
                )
        return results

    async def _fetch_single(self, event_id: str) -> BetfairEnrichment | None:
        async with self._semaphore:
            headers = {
                "X-Application": self._app_key,
                "X-Authentication": self._session_token,
                "Content-Type": "application/json",
            }
            payload = {
                "jsonrpc": "2.0",
                "method": "SportsAPING/v1.0/listMarketBook",
                "params": {
                    "marketIds": [event_id],
                    "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
                },
            }
            response = await self._client.post(
                f"{self._base_url}/betting/rest/v1.0/",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            markets = data.get("result", [])
            if not markets:
                return None

            market = markets[0]
            matched = market.get("totalMatched", 0.0)
            runners = market.get("runners", [])

            back_home = back_draw = back_away = None
            for i, runner in enumerate(runners):
                best_back = runner.get("ex", {}).get("availableToBack", [])
                amount = best_back[0].get("size", 0.0) if best_back else 0.0
                if i == 0:
                    back_home = amount
                elif i == 1:
                    back_draw = amount
                elif i == 2:
                    back_away = amount

            return BetfairEnrichment(
                event_id=event_id,
                matched_amount=matched,
                back_available_home=back_home,
                back_available_draw=back_draw,
                back_available_away=back_away,
            )

    async def close(self) -> None:
        await self._client.aclose()
