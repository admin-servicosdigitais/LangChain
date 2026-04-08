from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from value_betting_shared.models.enums import (
    CollectionStatusEnum,
    ComponentNameEnum,
    ComponentStatusEnum,
    QualityAlertTypeEnum,
    SeverityEnum,
)


class ComponentHealth(BaseModel):
    name: ComponentNameEnum
    status: ComponentStatusEnum
    last_check_at: datetime
    details: str | None = None


class CollectionHealth(BaseModel):
    status: CollectionStatusEnum
    last_successful_run: datetime | None = None
    current_cycle_running: bool = False
    consecutive_failures: int = Field(default=0, ge=0)
    active_events_count: int = Field(default=0, ge=0)
    markets_per_minute: float = 0.0
    average_cycle_duration_ms: float = 0.0
    components: list[ComponentHealth] = Field(default_factory=list)


class QualityAlert(BaseModel):
    quality_alert_id: str
    league_id: str | None = None
    bookmaker_id: str | None = None
    alert_type: QualityAlertTypeEnum
    detected_at: datetime
    severity: SeverityEnum
    metric_value: float
    threshold_value: float
