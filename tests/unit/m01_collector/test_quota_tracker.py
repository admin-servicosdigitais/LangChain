from __future__ import annotations

from unittest.mock import MagicMock

from value_betting_collector.services.quota_tracker import QuotaTracker
from value_betting_shared.models.enums import AlertLevelEnum


class TestQuotaTracker:
    def _make_table(self, current_count: int) -> MagicMock:
        table = MagicMock()
        table.update_item.return_value = {
            "Attributes": {"requests_count": current_count}
        }
        return table

    def test_normal_usage_returns_none(self):
        table = self._make_table(100_000)
        tracker = QuotaTracker(table, monthly_limit=500_000)
        result = tracker.increment(100)
        assert result is None

    def test_warning_at_80_pct(self):
        table = self._make_table(400_001)
        tracker = QuotaTracker(table, monthly_limit=500_000)
        result = tracker.increment(1)
        assert result == AlertLevelEnum.WARNING

    def test_critical_at_95_pct(self):
        table = self._make_table(475_001)
        tracker = QuotaTracker(table, monthly_limit=500_000)
        result = tracker.increment(1)
        assert result == AlertLevelEnum.CRITICAL

    def test_get_current_usage(self):
        table = MagicMock()
        table.get_item.return_value = {
            "Item": {"requests_count": 250_000}
        }
        tracker = QuotaTracker(table, monthly_limit=500_000)
        count, month = tracker.get_current_usage()
        assert count == 250_000
        assert len(month) == 7  # YYYY-MM
