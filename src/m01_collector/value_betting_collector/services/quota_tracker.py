from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from value_betting_shared.models.enums import AlertLevelEnum

logger = logging.getLogger(__name__)


class QuotaTracker:
    def __init__(
        self,
        table: Any,
        monthly_limit: int,
        warning_pct: float = 80.0,
        critical_pct: float = 95.0,
    ) -> None:
        self._table = table
        self._monthly_limit = monthly_limit
        self._warning_pct = warning_pct
        self._critical_pct = critical_pct

    def increment(self, count: int) -> AlertLevelEnum | None:
        month_key = datetime.now(UTC).strftime("%Y-%m")
        response = self._table.update_item(
            Key={"pk": "quota", "sk": month_key},
            UpdateExpression="ADD requests_count :inc",
            ExpressionAttributeValues={":inc": count},
            ReturnValues="UPDATED_NEW",
        )
        new_count = int(response["Attributes"]["requests_count"])
        pct = (new_count / self._monthly_limit) * 100 if self._monthly_limit > 0 else 0

        if pct >= self._critical_pct:
            logger.critical(
                "Quota CRITICAL: %.1f%% (%d/%d)",
                pct,
                new_count,
                self._monthly_limit,
            )
            return AlertLevelEnum.CRITICAL
        if pct >= self._warning_pct:
            logger.warning(
                "Quota WARNING: %.1f%% (%d/%d)",
                pct,
                new_count,
                self._monthly_limit,
            )
            return AlertLevelEnum.WARNING
        return None

    def get_current_usage(self) -> tuple[int, str]:
        month_key = datetime.now(UTC).strftime("%Y-%m")
        response = self._table.get_item(Key={"pk": "quota", "sk": month_key})
        item = response.get("Item", {})
        count = int(item.get("requests_count", 0))
        return count, month_key
