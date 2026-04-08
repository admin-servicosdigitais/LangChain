from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from value_betting_collector.orchestrator import CollectionOrchestrator
from value_betting_collector.services.quality_monitor import QualityMonitor
from value_betting_collector.sources.base import (
    BetfairEnrichment,
    FetchResult,
    MatchContext,
    RawOddsData,
)
from value_betting_shared.models.enums import (
    MarketTypeEnum,
    OddsSourceEnum,
)


def _settings() -> MagicMock:
    s = MagicMock()
    s.low_liquidity_threshold_usd = 10_000.0
    return s


def _raw(
    event_id: str = "ev1",
    bookmaker_id: str = "bet365",
    is_pinnacle: bool = False,
    odds_home: float = 2.10,
    odds_draw: float = 3.40,
    odds_away: float = 3.60,
) -> RawOddsData:
    return RawOddsData(
        event_id=event_id,
        sport="soccer",
        league_id="epl",
        home_team="TeamA",
        away_team="TeamB",
        commence_time="2026-04-08T15:00:00Z",
        bookmaker_id=bookmaker_id,
        market_type=MarketTypeEnum.ONE_X_TWO,
        odds_home=odds_home,
        odds_draw=odds_draw,
        odds_away=odds_away,
        source=OddsSourceEnum.THE_ODDS_API,
        is_pinnacle=is_pinnacle,
    )


def _make_orchestrator(
    writer: AsyncMock | None = None,
    detector: AsyncMock | None = None,
    quality: QualityMonitor | None = None,
) -> CollectionOrchestrator:
    w = writer or AsyncMock(write_batch=AsyncMock(return_value=0))
    d = detector or AsyncMock(detect_and_publish=AsyncMock(return_value=0))
    q = quality or QualityMonitor()
    return CollectionOrchestrator(
        settings=_settings(),
        snapshot_writer=w,
        movement_detector=d,
        quality_monitor=q,
    )


class TestExtractPinnacle:
    def test_extracts_only_pinnacle_entries(self):
        orch = _make_orchestrator()
        odds = [
            _raw(event_id="ev1", is_pinnacle=True, odds_home=2.05),
            _raw(event_id="ev1", is_pinnacle=False),
            _raw(event_id="ev2", is_pinnacle=True, odds_home=1.90),
        ]
        result = orch._extract_pinnacle(odds)
        assert len(result) == 2
        assert "ev1#1x2" in result
        assert "ev2#1x2" in result
        assert result["ev1#1x2"].home == 2.05

    def test_empty_odds_returns_empty_dict(self):
        orch = _make_orchestrator()
        assert orch._extract_pinnacle([]) == {}


class TestCalcMargin:
    def test_three_way_margin(self):
        from value_betting_shared.models.odds import PinnacleOdds

        orch = _make_orchestrator()
        odds = PinnacleOdds(home=2.05, draw=3.35, away=3.55)
        margin = orch._calc_margin(odds)
        expected = round((1 / 2.05) + (1 / 3.35) + (1 / 3.55) - 1, 4)
        assert margin == expected

    def test_two_way_margin(self):
        from value_betting_shared.models.odds import PinnacleOdds

        orch = _make_orchestrator()
        odds = PinnacleOdds(home=1.90, draw=None, away=2.00)
        margin = orch._calc_margin(odds)
        expected = round((1 / 1.90) + (1 / 2.00) - 1, 4)
        assert margin == expected


class TestBuildSnapshot:
    def test_snapshot_without_pinnacle_is_no_sharp(self):
        orch = _make_orchestrator()
        raw = _raw()
        snap = orch._build_snapshot(
            raw=raw,
            pinnacle=None,
            enrichment=None,
            context=None,
            collected_at=datetime.now(UTC),
        )
        assert snap.no_sharp_reference is True
        assert snap.pinnacle_odds is None
        assert snap.pinnacle_margin is None

    def test_snapshot_with_betfair_enrichment(self):
        orch = _make_orchestrator()
        raw = _raw()
        enrichment = BetfairEnrichment(
            event_id="ev1",
            matched_amount=5000.0,
            back_available_home=100.0,
            back_available_away=80.0,
        )
        snap = orch._build_snapshot(
            raw=raw,
            pinnacle=None,
            enrichment=enrichment,
            context=None,
            collected_at=datetime.now(UTC),
        )
        assert snap.low_liquidity is True
        assert snap.betfair_matched_amount == 5000.0

    def test_snapshot_with_match_context(self):
        orch = _make_orchestrator()
        raw = _raw()
        ctx = MatchContext(event_id="ev1", status="scheduled", venue="Wembley")
        snap = orch._build_snapshot(
            raw=raw,
            pinnacle=None,
            enrichment=None,
            context=ctx,
            collected_at=datetime.now(UTC),
        )
        assert snap.match_venue == "Wembley"


class TestProcessCollection:
    @pytest.mark.asyncio
    async def test_skips_pinnacle_from_snapshots(self):
        writer = AsyncMock()
        writer.write_batch = AsyncMock(return_value=1)
        detector = AsyncMock()
        detector.detect_and_publish = AsyncMock(return_value=0)

        orch = _make_orchestrator(writer=writer, detector=detector)
        fetch = FetchResult(
            odds=[
                _raw(event_id="ev1", is_pinnacle=True),
                _raw(event_id="ev1", is_pinnacle=False),
            ],
            requests_used=1,
        )
        await orch.process_collection(fetch)

        written_snapshots = writer.write_batch.call_args[0][0]
        assert len(written_snapshots) == 1
        assert written_snapshots[0].event_id == "ev1"

    @pytest.mark.asyncio
    async def test_returns_requests_used_and_errors(self):
        orch = _make_orchestrator()
        fetch = FetchResult(
            odds=[],
            requests_used=5,
            errors=["some error"],
        )
        result = await orch.process_collection(fetch)
        assert result.requests_used == 5
        assert result.errors == ["some error"]

    @pytest.mark.asyncio
    async def test_quality_alerts_for_low_pinnacle_coverage(self):
        quality = QualityMonitor(pinnacle_coverage_min_pct=50.0)
        orch = _make_orchestrator(quality=quality)
        fetch = FetchResult(
            odds=[
                _raw(event_id="ev1", is_pinnacle=False),
                _raw(event_id="ev2", is_pinnacle=False),
                _raw(event_id="ev3", is_pinnacle=False),
            ],
        )
        result = await orch.process_collection(fetch)
        assert len(result.quality_alerts) == 1
        assert result.quality_alerts[0].league_id == "epl"
