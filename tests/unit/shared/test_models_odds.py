from __future__ import annotations

from datetime import UTC, datetime

import pytest
from value_betting_shared.models.enums import MarketTypeEnum, OddsSourceEnum
from value_betting_shared.models.odds import (
    OddsMovementEvent,
    OddsSnapshot,
    PinnacleOdds,
)


def _make_snapshot(**overrides):
    defaults = {
        "event_id": "match_001",
        "market_type": MarketTypeEnum.ONE_X_TWO,
        "bookmaker_id": "bet365",
        "odds_home": 2.10,
        "odds_draw": 3.40,
        "odds_away": 3.60,
        "pinnacle_odds": PinnacleOdds(home=2.05, draw=3.35, away=3.55),
        "collected_at": datetime(2026, 4, 7, 14, 0, 0, tzinfo=UTC),
        "source": OddsSourceEnum.THE_ODDS_API,
    }
    defaults.update(overrides)
    return OddsSnapshot(**defaults)


class TestPinnacleOdds:
    def test_valid_pinnacle(self):
        p = PinnacleOdds(home=1.85, draw=3.40, away=4.20)
        assert p.home == 1.85
        assert p.draw == 3.40

    def test_odds_must_be_greater_than_1(self):
        with pytest.raises(ValueError):
            PinnacleOdds(home=0.5, away=2.0)

    def test_draw_is_optional(self):
        p = PinnacleOdds(home=1.85, away=2.10)
        assert p.draw is None


class TestOddsSnapshot:
    def test_valid_snapshot(self):
        snap = _make_snapshot()
        assert snap.event_id == "match_001"
        assert snap.no_sharp_reference is False
        assert snap.pinnacle_odds is not None

    def test_pinnacle_required_when_not_no_sharp(self):
        with pytest.raises(ValueError, match="pinnacle_odds"):
            _make_snapshot(pinnacle_odds=None, no_sharp_reference=False)

    def test_no_sharp_reference_allows_null_pinnacle(self):
        snap = _make_snapshot(pinnacle_odds=None, no_sharp_reference=True)
        assert snap.pinnacle_odds is None
        assert snap.no_sharp_reference is True

    def test_ttl_auto_calculated(self):
        snap = _make_snapshot()
        assert snap.expires_at > 0
        expected_min = int(
            datetime(2027, 5, 1, tzinfo=UTC).timestamp()
        )
        assert snap.expires_at > expected_min - 86400 * 30

    def test_sort_key_format(self):
        snap = _make_snapshot()
        assert snap.sort_key == "2026-04-07T14:00:00Z#the_odds_api"

    def test_to_dynamodb_item(self):
        snap = _make_snapshot()
        item = snap.to_dynamodb_item()
        assert item["event_id"] == "match_001"
        assert item["sort_key"] == "2026-04-07T14:00:00Z#the_odds_api"
        assert item["market_type"] == "1x2"
        assert isinstance(item["pinnacle_odds"], dict)

    def test_low_liquidity_default_false(self):
        snap = _make_snapshot()
        assert snap.low_liquidity is False

    def test_high_volatility_default_false(self):
        snap = _make_snapshot()
        assert snap.high_volatility is False


class TestOddsMovementEvent:
    def test_movement_event(self):
        evt = OddsMovementEvent(
            event_id="match_001",
            market_type=MarketTypeEnum.ONE_X_TWO,
            bookmaker_id="pinnacle",
            previous_odds=PinnacleOdds(home=1.85, draw=3.40, away=4.20),
            current_odds=PinnacleOdds(home=1.95, draw=3.30, away=4.00),
            delta_pct=3.3,
        )
        assert evt.delta_pct == 3.3
        assert evt.collected_at is not None
