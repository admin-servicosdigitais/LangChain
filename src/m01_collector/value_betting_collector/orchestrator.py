from __future__ import annotations

import contextlib
import logging
from collections import defaultdict
from datetime import UTC, datetime

from value_betting_shared.models.enums import (
    MatchStatusEnum,
)
from value_betting_shared.models.health import QualityAlert
from value_betting_shared.models.odds import (
    ExchangeBackAvailable,
    OddsSnapshot,
    PinnacleOdds,
)

from value_betting_collector.config import CollectorSettings
from value_betting_collector.services.movement_detector import MovementDetector
from value_betting_collector.services.quality_monitor import QualityMonitor
from value_betting_collector.services.snapshot_writer import SnapshotWriter
from value_betting_collector.sources.base import (
    BetfairEnrichment,
    FetchResult,
    MatchContext,
    RawOddsData,
)

logger = logging.getLogger(__name__)


class CollectionOrchestrator:
    def __init__(
        self,
        settings: CollectorSettings,
        snapshot_writer: SnapshotWriter,
        movement_detector: MovementDetector,
        quality_monitor: QualityMonitor,
    ) -> None:
        self._settings = settings
        self._writer = snapshot_writer
        self._detector = movement_detector
        self._quality = quality_monitor

    async def process_collection(
        self,
        fetch_result: FetchResult,
        betfair_data: list[BetfairEnrichment] | None = None,
        match_contexts: list[MatchContext] | None = None,
    ) -> CollectionResult:
        now = datetime.now(UTC)
        betfair_map = self._build_betfair_map(betfair_data or [])
        context_map = self._build_context_map(match_contexts or [])

        pinnacle_by_event = self._extract_pinnacle(fetch_result.odds)
        snapshots: list[OddsSnapshot] = []

        for raw in fetch_result.odds:
            if raw.is_pinnacle:
                continue

            pinnacle = pinnacle_by_event.get(
                f"{raw.event_id}#{raw.market_type.value}"
            )
            enrichment = betfair_map.get(raw.event_id)
            context = context_map.get(raw.event_id)

            snapshot = self._build_snapshot(
                raw=raw,
                pinnacle=pinnacle,
                enrichment=enrichment,
                context=context,
                collected_at=now,
            )
            snapshots.append(snapshot)

        quality_alerts = self._check_quality(fetch_result.odds)

        written = await self._writer.write_batch(snapshots)
        movements = await self._detector.detect_and_publish(snapshots)

        return CollectionResult(
            snapshots_written=written,
            movements_published=movements,
            errors=fetch_result.errors,
            requests_used=fetch_result.requests_used,
            quality_alerts=quality_alerts,
        )

    def _extract_pinnacle(
        self,
        odds: list[RawOddsData],
    ) -> dict[str, PinnacleOdds]:
        result: dict[str, PinnacleOdds] = {}
        for raw in odds:
            if raw.is_pinnacle:
                key = f"{raw.event_id}#{raw.market_type.value}"
                result[key] = PinnacleOdds(
                    home=raw.odds_home,
                    draw=raw.odds_draw,
                    away=raw.odds_away,
                )
        return result

    def _build_betfair_map(
        self,
        data: list[BetfairEnrichment],
    ) -> dict[str, BetfairEnrichment]:
        return {d.event_id: d for d in data}

    def _build_context_map(
        self,
        contexts: list[MatchContext],
    ) -> dict[str, MatchContext]:
        return {c.event_id: c for c in contexts}

    def _build_snapshot(
        self,
        raw: RawOddsData,
        pinnacle: PinnacleOdds | None,
        enrichment: BetfairEnrichment | None,
        context: MatchContext | None,
        collected_at: datetime,
    ) -> OddsSnapshot:
        no_sharp = pinnacle is None
        pinnacle_margin = self._calc_margin(pinnacle) if pinnacle else None

        matched_amount = enrichment.matched_amount if enrichment else None
        low_liquidity = (
            matched_amount is not None
            and matched_amount < self._settings.low_liquidity_threshold_usd
        )

        exchange_back = None
        if enrichment and enrichment.back_available_home is not None:
            exchange_back = ExchangeBackAvailable(
                home=enrichment.back_available_home or 0.0,
                draw=enrichment.back_available_draw,
                away=enrichment.back_available_away or 0.0,
            )

        match_status = None
        if context and context.status:
            with contextlib.suppress(ValueError):
                match_status = MatchStatusEnum(context.status)

        return OddsSnapshot(
            event_id=raw.event_id,
            market_type=raw.market_type,
            bookmaker_id=raw.bookmaker_id,
            odds_home=raw.odds_home,
            odds_draw=raw.odds_draw,
            odds_away=raw.odds_away,
            pinnacle_odds=pinnacle,
            pinnacle_margin=pinnacle_margin,
            no_sharp_reference=no_sharp,
            collected_at=collected_at,
            source=raw.source,
            betfair_matched_amount=matched_amount,
            betfair_available_to_back=exchange_back,
            exchange_volume_usd=matched_amount,
            exchange_back_available=exchange_back,
            low_liquidity=low_liquidity,
            match_status=match_status,
            match_venue=context.venue if context else None,
            match_round=context.round if context else None,
        )

    def _calc_margin(self, odds: PinnacleOdds) -> float:
        inv_sum = (1 / odds.home) + (1 / odds.away)
        if odds.draw:
            inv_sum += 1 / odds.draw
        return round(inv_sum - 1, 4)

    def _check_quality(
        self,
        odds: list[RawOddsData],
    ) -> list[QualityAlert]:
        alerts: list[QualityAlert] = []
        league_events: dict[str, set[str]] = defaultdict(set)
        league_pinnacle: dict[str, set[str]] = defaultdict(set)

        for raw in odds:
            league_events[raw.league_id].add(raw.event_id)
            if raw.is_pinnacle:
                league_pinnacle[raw.league_id].add(raw.event_id)

        for league_id, events in league_events.items():
            pinnacle_count = len(league_pinnacle.get(league_id, set()))
            alert = self._quality.check_pinnacle_coverage(
                league_id=league_id,
                total_events=len(events),
                pinnacle_events=pinnacle_count,
            )
            if alert:
                alerts.append(alert)

        return alerts


class CollectionResult:
    def __init__(
        self,
        snapshots_written: int = 0,
        movements_published: int = 0,
        errors: list[str] | None = None,
        requests_used: int = 0,
        quality_alerts: list[QualityAlert] | None = None,
    ) -> None:
        self.snapshots_written = snapshots_written
        self.movements_published = movements_published
        self.errors = errors or []
        self.requests_used = requests_used
        self.quality_alerts = quality_alerts or []
