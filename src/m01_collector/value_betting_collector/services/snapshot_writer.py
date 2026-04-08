from __future__ import annotations

import asyncio
import logging
from typing import Any

from value_betting_shared.models.odds import OddsSnapshot

logger = logging.getLogger(__name__)

_BATCH_SIZE = 25


class SnapshotWriter:
    def __init__(self, table: Any) -> None:
        self._table = table

    async def write_batch(self, snapshots: list[OddsSnapshot]) -> int:
        return await asyncio.to_thread(self._write_batch_sync, snapshots)

    def _write_batch_sync(self, snapshots: list[OddsSnapshot]) -> int:
        written = 0
        for i in range(0, len(snapshots), _BATCH_SIZE):
            batch = snapshots[i : i + _BATCH_SIZE]
            with self._table.batch_writer() as writer:
                for snapshot in batch:
                    item = snapshot.to_dynamodb_item()
                    writer.put_item(Item=self._serialize(item))
                    written += 1
        logger.info("Wrote %d snapshots to DynamoDB", written)
        return written

    def _serialize(self, item: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for k, v in item.items():
            if v is None:
                continue
            if isinstance(v, float):
                from decimal import Decimal

                cleaned[k] = Decimal(str(v))
            elif isinstance(v, dict):
                cleaned[k] = self._serialize(v)
            else:
                cleaned[k] = v
        return cleaned
