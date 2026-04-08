from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from value_betting_shared.models.degradation import DegradationStatus

logger = logging.getLogger(__name__)


class DegradationManager:
    def __init__(
        self,
        table: Any,
        max_consecutive_failures: int = 3,
    ) -> None:
        self._table = table
        self._max_failures = max_consecutive_failures

    def record_failure(self) -> DegradationStatus:
        response = self._table.update_item(
            Key={"pk": "collection_state", "sk": "degradation"},
            UpdateExpression=(
                "ADD consecutive_failures :one "
                "SET last_failure_at = :now"
            ),
            ExpressionAttributeValues={
                ":one": 1,
                ":now": datetime.now(UTC).isoformat(),
            },
            ReturnValues="ALL_NEW",
        )
        attrs = response["Attributes"]
        failures = int(attrs.get("consecutive_failures", 0))

        if failures >= self._max_failures and not attrs.get("active", False):
            self._activate_degraded_mode(reason="auto: 3 consecutive failures")
            return self.get_status()

        return self._attrs_to_status(attrs)

    def record_success(self) -> None:
        self._table.update_item(
            Key={"pk": "collection_state", "sk": "degradation"},
            UpdateExpression=(
                "SET consecutive_failures = :zero, "
                "last_success_at = :now, "
                "active = :false"
            ),
            ExpressionAttributeValues={
                ":zero": 0,
                ":now": datetime.now(UTC).isoformat(),
                ":false": False,
            },
        )

    def get_status(self) -> DegradationStatus:
        response = self._table.get_item(
            Key={"pk": "collection_state", "sk": "degradation"}
        )
        item = response.get("Item", {})
        return self._attrs_to_status(item)

    def _activate_degraded_mode(self, reason: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._table.update_item(
            Key={"pk": "collection_state", "sk": "degradation"},
            UpdateExpression=(
                "SET active = :true, "
                "activated_at = :now, "
                "activated_by = :system, "
                "reason = :reason, "
                "auto_activated = :true"
            ),
            ExpressionAttributeValues={
                ":true": True,
                ":now": now,
                ":system": "system",
                ":reason": reason,
            },
        )
        logger.critical("Degraded mode ACTIVATED: %s", reason)

    def _attrs_to_status(self, attrs: dict[str, Any]) -> DegradationStatus:
        activated_at = attrs.get("activated_at")
        return DegradationStatus(
            active=bool(attrs.get("active", False)),
            activated_at=datetime.fromisoformat(activated_at) if activated_at else None,
            activated_by=attrs.get("activated_by"),
            reason=attrs.get("reason"),
            auto_activated=bool(attrs.get("auto_activated", False)),
            affected_leagues=attrs.get("affected_leagues", []),
        )
