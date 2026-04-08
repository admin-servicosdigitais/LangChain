from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from value_betting_collector.services.snapshot_writer import SnapshotWriter
from value_betting_shared.models.enums import MarketTypeEnum, OddsSourceEnum
from value_betting_shared.models.odds import OddsSnapshot, PinnacleOdds


def _make_snapshot(event_id: str = "match_001") -> OddsSnapshot:
    return OddsSnapshot(
        event_id=event_id,
        market_type=MarketTypeEnum.ONE_X_TWO,
        bookmaker_id="bet365",
        odds_home=2.10,
        odds_draw=3.40,
        odds_away=3.60,
        pinnacle_odds=PinnacleOdds(home=2.05, draw=3.35, away=3.55),
        collected_at=datetime(2026, 4, 7, 14, 0, 0, tzinfo=UTC),
        source=OddsSourceEnum.THE_ODDS_API,
    )


class TestSnapshotWriter:
    def test_serialize_converts_floats_to_decimal(self):
        table = MagicMock()
        writer = SnapshotWriter(table=table)
        result = writer._serialize({"price": 2.10, "name": "test", "empty": None})
        assert isinstance(result["price"], Decimal)
        assert result["name"] == "test"
        assert "empty" not in result

    @pytest.mark.asyncio
    async def test_write_batch_calls_put_item(self):
        mock_batch_writer = MagicMock()
        mock_batch_writer.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_batch_writer.__exit__ = MagicMock(return_value=False)

        table = MagicMock()
        table.batch_writer.return_value = mock_batch_writer

        writer = SnapshotWriter(table=table)
        snapshots = [_make_snapshot(f"match_{i}") for i in range(3)]
        written = await writer.write_batch(snapshots)

        assert written == 3
        assert mock_batch_writer.put_item.call_count == 3

    @pytest.mark.asyncio
    async def test_write_empty_batch(self):
        table = MagicMock()
        writer = SnapshotWriter(table=table)
        written = await writer.write_batch([])
        assert written == 0
