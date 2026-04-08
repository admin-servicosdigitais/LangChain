from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from value_betting_shared.models.odds import (
    OddsMovementEvent,
    OddsSnapshot,
    PinnacleOdds,
)

logger = logging.getLogger(__name__)


class MovementDetector:
    def __init__(
        self,
        sqs_client: Any,
        queue_url: str,
        threshold_pct: float = 2.0,
    ) -> None:
        self._sqs = sqs_client
        self._queue_url = queue_url
        self._threshold_pct = threshold_pct
        self._previous_cache: dict[str, PinnacleOdds] = {}

    def set_previous_odds(
        self,
        cache: dict[str, PinnacleOdds],
    ) -> None:
        self._previous_cache = cache

    async def detect_and_publish(
        self,
        snapshots: list[OddsSnapshot],
    ) -> int:
        published = 0
        for snap in snapshots:
            if snap.pinnacle_odds is None or snap.no_sharp_reference:
                continue

            cache_key = f"{snap.event_id}#{snap.market_type.value}"
            previous = self._previous_cache.get(cache_key)

            if previous is None:
                self._previous_cache[cache_key] = snap.pinnacle_odds
                continue

            delta_pct = self._calc_delta_pct(previous, snap.pinnacle_odds)
            if abs(delta_pct) > self._threshold_pct:
                event = OddsMovementEvent(
                    event_id=snap.event_id,
                    event_canonical_id=snap.event_canonical_id,
                    market_type=snap.market_type,
                    bookmaker_id="pinnacle",
                    previous_odds=previous,
                    current_odds=snap.pinnacle_odds,
                    delta_pct=delta_pct,
                    collected_at=datetime.now(UTC),
                )
                await self._publish(event, snap)
                published += 1

            self._previous_cache[cache_key] = snap.pinnacle_odds

        if published:
            logger.info("Published %d movement events", published)
        return published

    def _calc_delta_pct(
        self,
        prev: PinnacleOdds,
        curr: PinnacleOdds,
    ) -> float:
        prev_avg = (prev.home + prev.away) / 2
        curr_avg = (curr.home + curr.away) / 2
        if prev_avg == 0:
            return 0.0
        return ((curr_avg - prev_avg) / prev_avg) * 100

    async def _publish(
        self,
        event: OddsMovementEvent,
        snapshot: OddsSnapshot,
    ) -> None:
        body = event.model_dump_json()
        dedup_id = hashlib.sha256(
            f"{snapshot.event_id}#{snapshot.collected_at.isoformat()}#{snapshot.source.value}".encode()
        ).hexdigest()[:128]

        await asyncio.to_thread(
            self._sqs.send_message,
            QueueUrl=self._queue_url,
            MessageBody=body,
            MessageGroupId=event.event_id,
            MessageDeduplicationId=dedup_id,
        )
