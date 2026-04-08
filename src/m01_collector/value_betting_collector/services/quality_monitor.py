from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from value_betting_shared.models.enums import (
    QualityAlertTypeEnum,
    SeverityEnum,
)
from value_betting_shared.models.health import QualityAlert
from value_betting_shared.models.odds import PinnacleOdds

logger = logging.getLogger(__name__)


class QualityMonitor:
    def __init__(
        self,
        pinnacle_coverage_min_pct: float = 50.0,
        volatility_threshold_pct: float = 15.0,
        unreliable_coverage_pct: float = 10.0,
        unreliable_consecutive: int = 3,
    ) -> None:
        self._pinnacle_min_pct = pinnacle_coverage_min_pct
        self._volatility_pct = volatility_threshold_pct
        self._unreliable_pct = unreliable_coverage_pct
        self._unreliable_consecutive = unreliable_consecutive
        self._bookmaker_miss_counter: dict[str, int] = {}

    def check_pinnacle_coverage(
        self,
        league_id: str,
        total_events: int,
        pinnacle_events: int,
    ) -> QualityAlert | None:
        if total_events == 0:
            return None
        coverage = (pinnacle_events / total_events) * 100
        if coverage < self._pinnacle_min_pct:
            logger.warning(
                "Pinnacle coverage low for %s: %.1f%%",
                league_id,
                coverage,
            )
            return QualityAlert(
                quality_alert_id=str(uuid.uuid4()),
                league_id=league_id,
                alert_type=QualityAlertTypeEnum.PINNACLE_COVERAGE_LOW,
                detected_at=datetime.now(UTC),
                severity=SeverityEnum.WARNING,
                metric_value=coverage,
                threshold_value=self._pinnacle_min_pct,
            )
        return None

    def check_volatility(
        self,
        event_id: str,
        previous: PinnacleOdds,
        current: PinnacleOdds,
    ) -> bool:
        prev_avg = (previous.home + previous.away) / 2
        curr_avg = (current.home + current.away) / 2
        if prev_avg == 0:
            return False
        delta_pct = abs((curr_avg - prev_avg) / prev_avg) * 100
        return delta_pct > self._volatility_pct

    def check_bookmaker_reliability(
        self,
        bookmaker_id: str,
        expected_markets: int,
        actual_markets: int,
    ) -> QualityAlert | None:
        if expected_markets == 0:
            return None
        coverage = (actual_markets / expected_markets) * 100
        if coverage < self._unreliable_pct:
            self._bookmaker_miss_counter[bookmaker_id] = (
                self._bookmaker_miss_counter.get(bookmaker_id, 0) + 1
            )
        else:
            self._bookmaker_miss_counter[bookmaker_id] = 0

        if self._bookmaker_miss_counter.get(bookmaker_id, 0) >= self._unreliable_consecutive:
            logger.warning("Bookmaker %s marked unreliable", bookmaker_id)
            return QualityAlert(
                quality_alert_id=str(uuid.uuid4()),
                bookmaker_id=bookmaker_id,
                alert_type=QualityAlertTypeEnum.BOOKMAKER_UNRELIABLE,
                detected_at=datetime.now(UTC),
                severity=SeverityEnum.CRITICAL,
                metric_value=coverage,
                threshold_value=self._unreliable_pct,
            )
        return None
