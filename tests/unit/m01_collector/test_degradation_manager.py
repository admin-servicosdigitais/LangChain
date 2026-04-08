from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from value_betting_collector.services.degradation import DegradationManager


def _table_with_item(item: dict | None = None) -> MagicMock:
    table = MagicMock()
    table.get_item.return_value = {"Item": item or {}}
    return table


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_returns_inactive_when_no_item(self):
        table = _table_with_item({})
        mgr = DegradationManager(table=table)
        status = await mgr.get_status()
        assert status.active is False

    @pytest.mark.asyncio
    async def test_returns_active_status(self):
        table = _table_with_item({
            "active": True,
            "activated_at": "2026-04-08T10:00:00+00:00",
            "activated_by": "system",
            "reason": "auto: 3 consecutive failures",
            "auto_activated": True,
        })
        mgr = DegradationManager(table=table)
        status = await mgr.get_status()
        assert status.active is True
        assert status.activated_by == "system"
        assert status.auto_activated is True


class TestRecordSuccess:
    @pytest.mark.asyncio
    async def test_resets_failures_and_deactivates(self):
        table = MagicMock()
        mgr = DegradationManager(table=table)
        await mgr.record_success()
        table.update_item.assert_called_once()
        call_kwargs = table.update_item.call_args[1]
        assert ":zero" in call_kwargs["ExpressionAttributeValues"]
        assert call_kwargs["ExpressionAttributeValues"][":zero"] == 0
        assert call_kwargs["ExpressionAttributeValues"][":false"] is False


class TestRecordFailure:
    @pytest.mark.asyncio
    async def test_does_not_activate_below_threshold(self):
        table = MagicMock()
        table.update_item.return_value = {
            "Attributes": {"consecutive_failures": 1, "active": False},
        }
        mgr = DegradationManager(table=table, max_consecutive_failures=3)
        status = await mgr.record_failure()
        assert status.active is False

    @pytest.mark.asyncio
    async def test_activates_at_threshold(self):
        table = MagicMock()
        table.update_item.return_value = {
            "Attributes": {"consecutive_failures": 3, "active": False},
        }
        table.get_item.return_value = {
            "Item": {
                "active": True,
                "activated_at": "2026-04-08T10:00:00+00:00",
                "activated_by": "system",
                "reason": "auto: 3 consecutive failures",
                "auto_activated": True,
            },
        }
        mgr = DegradationManager(table=table, max_consecutive_failures=3)
        status = await mgr.record_failure()
        assert status.active is True
        assert table.update_item.call_count == 2

    @pytest.mark.asyncio
    async def test_does_not_reactivate_if_already_active(self):
        table = MagicMock()
        table.update_item.return_value = {
            "Attributes": {"consecutive_failures": 5, "active": True},
        }
        mgr = DegradationManager(table=table, max_consecutive_failures=3)
        status = await mgr.record_failure()
        assert table.update_item.call_count == 1
