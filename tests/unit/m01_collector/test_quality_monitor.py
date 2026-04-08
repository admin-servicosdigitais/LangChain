from __future__ import annotations

from value_betting_collector.services.quality_monitor import QualityMonitor
from value_betting_shared.models.enums import QualityAlertTypeEnum
from value_betting_shared.models.odds import PinnacleOdds


class TestQualityMonitor:
    def test_pinnacle_coverage_ok(self):
        monitor = QualityMonitor(pinnacle_coverage_min_pct=50.0)
        alert = monitor.check_pinnacle_coverage("premier_league", 10, 8)
        assert alert is None

    def test_pinnacle_coverage_low(self):
        monitor = QualityMonitor(pinnacle_coverage_min_pct=50.0)
        alert = monitor.check_pinnacle_coverage("premier_league", 10, 3)
        assert alert is not None
        assert alert.alert_type == QualityAlertTypeEnum.PINNACLE_COVERAGE_LOW
        assert alert.metric_value == 30.0

    def test_pinnacle_coverage_zero_events(self):
        monitor = QualityMonitor()
        alert = monitor.check_pinnacle_coverage("premier_league", 0, 0)
        assert alert is None

    def test_volatility_detected(self):
        monitor = QualityMonitor(volatility_threshold_pct=15.0)
        prev = PinnacleOdds(home=2.00, away=3.00)
        curr = PinnacleOdds(home=2.50, away=3.60)
        assert monitor.check_volatility("evt_1", prev, curr) is True

    def test_volatility_within_threshold(self):
        monitor = QualityMonitor(volatility_threshold_pct=15.0)
        prev = PinnacleOdds(home=2.00, away=3.00)
        curr = PinnacleOdds(home=2.05, away=3.05)
        assert monitor.check_volatility("evt_1", prev, curr) is False

    def test_bookmaker_unreliable_after_consecutive(self):
        monitor = QualityMonitor(
            unreliable_coverage_pct=10.0,
            unreliable_consecutive=3,
        )
        for _ in range(2):
            alert = monitor.check_bookmaker_reliability("bad_bk", 100, 5)
            assert alert is None

        alert = monitor.check_bookmaker_reliability("bad_bk", 100, 5)
        assert alert is not None
        assert alert.alert_type == QualityAlertTypeEnum.BOOKMAKER_UNRELIABLE

    def test_bookmaker_resets_counter_on_good_coverage(self):
        monitor = QualityMonitor(
            unreliable_coverage_pct=10.0,
            unreliable_consecutive=3,
        )
        monitor.check_bookmaker_reliability("bk", 100, 5)
        monitor.check_bookmaker_reliability("bk", 100, 5)
        monitor.check_bookmaker_reliability("bk", 100, 50)
        alert = monitor.check_bookmaker_reliability("bk", 100, 5)
        assert alert is None
