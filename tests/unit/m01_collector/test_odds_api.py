from __future__ import annotations

import httpx
import pytest
from value_betting_collector.sources.odds_api import TheOddsApiClient
from value_betting_shared.models.enums import MarketTypeEnum

MOCK_RESPONSE = [
    {
        "id": "evt_001",
        "sport_key": "soccer_epl",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "commence_time": "2026-04-07T15:00:00Z",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Arsenal", "price": 1.85},
                            {"name": "Chelsea", "price": 4.20},
                            {"name": "Draw", "price": 3.40},
                        ],
                    }
                ],
            },
            {
                "key": "bet365",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Arsenal", "price": 1.90},
                            {"name": "Chelsea", "price": 4.00},
                            {"name": "Draw", "price": 3.50},
                        ],
                    }
                ],
            },
        ],
    }
]


@pytest.fixture
def mock_transport():
    return httpx.MockTransport(
        lambda request: httpx.Response(200, json=MOCK_RESPONSE)
    )


@pytest.fixture
def client(mock_transport):
    http_client = httpx.AsyncClient(transport=mock_transport)
    return TheOddsApiClient(
        api_key="test_key",
        base_url="https://api.test.com/v4",
        client=http_client,
    )


@pytest.mark.asyncio
async def test_fetch_odds_returns_data(client):
    result = await client.fetch_odds(
        sport="soccer_epl",
        league_ids=["soccer_epl"],
        market_types=[MarketTypeEnum.ONE_X_TWO],
    )
    assert len(result.odds) > 0
    assert result.requests_used == 1
    assert len(result.errors) == 0


@pytest.mark.asyncio
async def test_pinnacle_identified(client):
    result = await client.fetch_odds(
        sport="soccer_epl",
        league_ids=["soccer_epl"],
        market_types=[MarketTypeEnum.ONE_X_TWO],
    )
    pinnacle_odds = [o for o in result.odds if o.is_pinnacle]
    non_pinnacle = [o for o in result.odds if not o.is_pinnacle]
    assert len(pinnacle_odds) == 1
    assert len(non_pinnacle) == 1
    assert pinnacle_odds[0].odds_home == 1.85


@pytest.mark.asyncio
async def test_rate_limit_backoff():
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return httpx.Response(429)
        return httpx.Response(200, json=MOCK_RESPONSE)

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = TheOddsApiClient(
        api_key="test",
        base_url="https://api.test.com/v4",
        client=http_client,
    )

    result = await client.fetch_odds(
        sport="soccer",
        league_ids=[],
        market_types=[MarketTypeEnum.ONE_X_TWO],
    )
    assert call_count == 3
    assert len(result.odds) > 0


@pytest.mark.asyncio
async def test_request_error_captured():
    def handler(request):
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = TheOddsApiClient(
        api_key="test",
        base_url="https://api.test.com/v4",
        client=http_client,
    )

    result = await client.fetch_odds(
        sport="soccer",
        league_ids=[],
        market_types=[MarketTypeEnum.ONE_X_TWO],
    )
    assert len(result.errors) > 0
    assert len(result.odds) == 0
