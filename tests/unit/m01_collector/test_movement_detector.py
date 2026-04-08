from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from value_betting_collector.services.movement_detector import MovementDetector
from value_betting_shared.models.enums import MarketTypeEnum, OddsSourceEnum
from value_betting_shared.models.odds import OddsSnapshot, PinnacleOdds


def _snap(home: float, away: float, draw: float = 3.40) -> OddsSnapshot:
    return OddsSnapshot(
        event_id="match_001",
        market_type=MarketTypeEnum.ONE_X_TWO,
        bookmaker_id="bet365",
        odds_home=home,
        odds_draw=draw,
        odds_away=away,
        pinnacle_odds=PinnacleOdds(home=home, draw=draw, away=away),
        collected_at=datetime(2026, 4, 7, 14, 0, 0, tzinfo=UTC),
        source=OddsSourceEnum.THE_ODDS_API,
    )


class TestMovementDetector:
    @pytest.mark.asyncio
    async def test_no_movement_below_threshold(self):
        sqs = MagicMock()
        detector = MovementDetector(sqs, "queue_url", threshold_pct=2.0)

        first = _snap(2.00, 3.00)
        second = _snap(2.01, 3.01)

        await detector.detect_and_publish([first])
        published = await detector.detect_and_publish([second])

        assert published == 0
        sqs.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_movement_above_threshold_publishes(self):
        sqs = MagicMock()
        detector = MovementDetector(sqs, "queue_url", threshold_pct=2.0)

        first = _snap(2.00, 3.00)
        second = _snap(2.20, 3.30)

        await detector.detect_and_publish([first])
        published = await detector.detect_and_publish([second])

        assert published == 1
        sqs.send_message.assert_called_once()
        call_kwargs = sqs.send_message.call_args[1]
        assert call_kwargs["QueueUrl"] == "queue_url"
        assert "match_001" in call_kwargs["MessageGroupId"]

    @pytest.mark.asyncio
    async def test_no_sharp_reference_skipped(self):
        sqs = MagicMock()
        detector = MovementDetector(sqs, "queue_url", threshold_pct=2.0)

        snap = OddsSnapshot(
            event_id="match_002",
            market_type=MarketTypeEnum.ONE_X_TWO,
            bookmaker_id="bet365",
            odds_home=2.10,
            odds_draw=3.40,
            odds_away=3.60,
            pinnacle_odds=None,
            no_sharp_reference=True,
            collected_at=datetime(2026, 4, 7, 14, 0, 0, tzinfo=UTC),
            source=OddsSourceEnum.THE_ODDS_API,
        )
        published = await detector.detect_and_publish([snap])
        assert published == 0

    @pytest.mark.asyncio
    async def test_first_snapshot_cached_not_published(self):
        sqs = MagicMock()
        detector = MovementDetector(sqs, "queue_url", threshold_pct=2.0)

        first = _snap(2.00, 3.00)
        published = await detector.detect_and_publish([first])

        assert published == 0
        sqs.send_message.assert_not_called()
