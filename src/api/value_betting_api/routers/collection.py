from __future__ import annotations

import calendar
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from fastapi import APIRouter, Depends, HTTPException, Query, status
from value_betting_shared.models.enums import (
    MarketTypeEnum,
    QualityAlertTypeEnum,
    SeverityEnum,
    SportEnum,
    TierEnum,
)
from value_betting_shared.schemas.requests import (
    DegradationActivateRequest,
    LeagueCreateRequest,
    LeaguePatchRequest,
    MarketTypePatchRequest,
    PollingConfigPatchRequest,
    PollingOverrideCreateRequest,
)

from value_betting_api.dependencies import verify_admin_jwt, verify_elite_api_key

admin_router = APIRouter()
elite_router = APIRouter()


def _get_dynamodb() -> Any:
    endpoint = os.environ.get("VB_DYNAMODB_ENDPOINT_URL")
    region = os.environ.get("VB_AWS_REGION", "us-east-1")
    kwargs: dict[str, str] = {"region_name": region}
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.resource("dynamodb", **kwargs)


def _get_table(name_env: str, default: str) -> Any:
    db = _get_dynamodb()
    return db.Table(os.environ.get(name_env, default))


# ──────────────────────────── Leagues ────────────────────────────


@admin_router.get("/leagues")
async def list_leagues(
    sport: SportEnum | None = None,
    active: bool | None = None,
    tier_required: TierEnum | None = Query(None, alias="tierRequired"),
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_LEAGUES_TABLE", "leagues")
    scan_kwargs: dict[str, Any] = {}

    items = table.scan(**scan_kwargs).get("Items", [])

    if sport:
        items = [i for i in items if i.get("sport") == sport.value]
    if active is not None:
        items = [i for i in items if i.get("active") == active]
    if tier_required:
        items = [i for i in items if i.get("tier_required") == tier_required.value]

    return {"data": items}


@admin_router.post("/leagues", status_code=201)
async def create_league(
    body: LeagueCreateRequest,
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_LEAGUES_TABLE", "leagues")

    existing = table.get_item(Key={"league_id": body.league_id}).get("Item")
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Liga {body.league_id} já existe",
        )

    item = {
        "league_id": body.league_id,
        "name": body.name,
        "sport": body.sport.value,
        "country": body.country,
        "active": True,
        "tier_required": body.tier_required.value,
        "min_markets_per_round": body.min_markets_per_round,
    }
    table.put_item(Item=item)
    return {"data": item}


@admin_router.patch("/leagues/{league_id}")
async def update_league(
    league_id: str,
    body: LeaguePatchRequest,
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_LEAGUES_TABLE", "leagues")
    existing = table.get_item(Key={"league_id": league_id}).get("Item")
    if not existing:
        raise HTTPException(status_code=404, detail="Liga não encontrada")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    if "tier_required" in updates:
        updates["tier_required"] = updates["tier_required"].value

    expr_parts = []
    attr_values: dict[str, Any] = {}
    attr_names: dict[str, str] = {}
    for k, v in updates.items():
        safe_key = f"#{k}"
        attr_names[safe_key] = k
        expr_parts.append(f"{safe_key} = :{k}")
        attr_values[f":{k}"] = v

    table.update_item(
        Key={"league_id": league_id},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=attr_values,
    )
    existing.update(updates)
    return {"data": existing}


@admin_router.delete("/leagues/{league_id}", status_code=204)
async def disable_league(
    league_id: str,
    _auth: dict = Depends(verify_admin_jwt),
) -> None:
    table = _get_table("VB_LEAGUES_TABLE", "leagues")
    existing = table.get_item(Key={"league_id": league_id}).get("Item")
    if not existing:
        raise HTTPException(status_code=404, detail="Liga não encontrada")

    table.update_item(
        Key={"league_id": league_id},
        UpdateExpression="SET active = :false",
        ExpressionAttributeValues={":false": False},
    )


# ──────────────────────────── Market Types ────────────────────────────


@admin_router.get("/market-types")
async def list_market_types(
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_MARKET_TYPES_TABLE", "market_types")
    items = table.scan().get("Items", [])
    return {"data": items}


@admin_router.patch("/market-types/{market_type_id}")
async def update_market_type(
    market_type_id: str,
    body: MarketTypePatchRequest,
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_MARKET_TYPES_TABLE", "market_types")
    existing = table.get_item(Key={"market_type_id": market_type_id}).get("Item")
    if not existing:
        raise HTTPException(status_code=404, detail="Tipo de mercado não encontrado")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    expr_parts = []
    attr_values: dict[str, Any] = {}
    for k, v in updates.items():
        expr_parts.append(f"{k} = :{k}")
        attr_values[f":{k}"] = v

    table.update_item(
        Key={"market_type_id": market_type_id},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeValues=attr_values,
    )
    existing.update(updates)
    return {"data": existing}


# ──────────────────────────── Polling Config ────────────────────────────


@admin_router.get("/polling/config")
async def get_polling_config(
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_CONFIG_TABLE", "collection_config")
    item = table.get_item(Key={"pk": "polling", "sk": "global"}).get("Item", {})
    config = {
        "pollingInterval24hSec": int(item.get("polling_interval_24h_sec", 30)),
        "pollingInterval72hSec": int(item.get("polling_interval_72h_sec", 300)),
        "pollingIntervalBeyond72hSec": int(item.get("polling_interval_beyond_72h_sec", 1800)),
    }
    return {"data": config}


@admin_router.patch("/polling/config")
async def update_polling_config(
    body: PollingConfigPatchRequest,
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_CONFIG_TABLE", "collection_config")
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    expr_parts = []
    attr_values: dict[str, Any] = {}
    for k, v in updates.items():
        expr_parts.append(f"{k} = :{k}")
        attr_values[f":{k}"] = v

    table.update_item(
        Key={"pk": "polling", "sk": "global"},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeValues=attr_values,
    )

    return await get_polling_config(_auth=_auth)


# ──────────────────────────── Polling Overrides ────────────────────────────


@admin_router.get("/polling/overrides")
async def list_polling_overrides(
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_POLLING_OVERRIDES_TABLE", "polling_overrides")
    items = table.scan().get("Items", [])
    return {"data": items}


@admin_router.post("/polling/overrides", status_code=201)
async def create_polling_override(
    body: PollingOverrideCreateRequest,
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_POLLING_OVERRIDES_TABLE", "polling_overrides")

    existing = table.get_item(
        Key={"league_id": body.league_id, "bookmaker_id": body.bookmaker_id}
    ).get("Item")
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Override para {body.league_id}/{body.bookmaker_id} já existe",
        )

    admin_id = _auth.get("sub", "unknown")
    item = {
        "league_id": body.league_id,
        "bookmaker_id": body.bookmaker_id,
        "interval_seconds": body.interval_seconds,
        "created_at": datetime.now(UTC).isoformat(),
        "created_by": admin_id,
    }
    table.put_item(Item=item)
    return {"data": item}


@admin_router.delete(
    "/polling/overrides/{league_id}/{bookmaker_id}",
    status_code=204,
)
async def delete_polling_override(
    league_id: str,
    bookmaker_id: str,
    _auth: dict = Depends(verify_admin_jwt),
) -> None:
    table = _get_table("VB_POLLING_OVERRIDES_TABLE", "polling_overrides")
    existing = table.get_item(
        Key={"league_id": league_id, "bookmaker_id": bookmaker_id}
    ).get("Item")
    if not existing:
        raise HTTPException(status_code=404, detail="Override não encontrado")

    table.delete_item(Key={"league_id": league_id, "bookmaker_id": bookmaker_id})


# ──────────────────────────── Health ────────────────────────────


@admin_router.get("/health")
async def get_collection_health(
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_STATE_TABLE", "collection_state")
    item = table.get_item(
        Key={"pk": "collection_state", "sk": "health"}
    ).get("Item", {})

    health = {
        "status": item.get("status", "healthy"),
        "lastSuccessfulRun": item.get("last_successful_run"),
        "currentCycleRunning": item.get("current_cycle_running", False),
        "consecutiveFailures": int(item.get("consecutive_failures", 0)),
        "activeEventsCount": int(item.get("active_events_count", 0)),
        "marketsPerMinute": float(item.get("markets_per_minute", 0)),
        "averageCycleDurationMs": float(item.get("average_cycle_duration_ms", 0)),
        "components": item.get("components", []),
    }
    return {"data": health}


@admin_router.get("/quality-alerts")
async def list_quality_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    severity: SeverityEnum | None = None,
    alert_type: QualityAlertTypeEnum | None = Query(None, alias="alertType"),
    from_dt: str | None = Query(None, alias="from"),
    to_dt: str | None = Query(None, alias="to"),
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_QUALITY_ALERTS_TABLE", "quality_alerts")
    items = table.scan().get("Items", [])

    if severity:
        items = [i for i in items if i.get("severity") == severity.value]
    if alert_type:
        items = [i for i in items if i.get("alert_type") == alert_type.value]

    total = len(items)
    start = (page - 1) * page_size
    paged = items[start : start + page_size]
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    return {
        "data": paged,
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "totalItems": total,
            "totalPages": total_pages,
        },
    }


@admin_router.get("/bookmakers/reliability")
async def list_bookmaker_reliability(
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_BOOKMAKER_RELIABILITY_TABLE", "bookmaker_reliability")
    items = table.scan().get("Items", [])
    return {"data": items}


# ──────────────────────────── Quota ────────────────────────────


@admin_router.get("/quota")
async def get_quota_usage(
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_QUOTA_TABLE", "api_quota")
    month_key = datetime.now(UTC).strftime("%Y-%m")
    item = table.get_item(Key={"pk": "quota", "sk": month_key}).get("Item", {})

    limit = int(os.environ.get("VB_ODDS_API_MONTHLY_LIMIT", "500000"))
    count = int(item.get("requests_count", 0))
    pct = (count / limit * 100) if limit > 0 else 0

    alert_level = None
    if pct >= 95:
        alert_level = "critical"
    elif pct >= 80:
        alert_level = "warning"

    return {
        "data": {
            "month": month_key,
            "requestsCount": count,
            "requestsLimit": limit,
            "percentageConsumed": round(pct, 1),
            "alertLevel": alert_level,
        }
    }


@admin_router.get("/quota/projection")
async def get_quota_projection(
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_QUOTA_TABLE", "api_quota")
    now = datetime.now(UTC)
    month_key = now.strftime("%Y-%m")
    item = table.get_item(Key={"pk": "quota", "sk": month_key}).get("Item", {})

    limit = int(os.environ.get("VB_ODDS_API_MONTHLY_LIMIT", "500000"))
    count = int(item.get("requests_count", 0))

    day_of_month = now.day
    days_in_month = calendar.monthrange(now.year, now.month)[1]

    if day_of_month > 0:
        daily_rate = count / day_of_month
        projected = int(daily_rate * days_in_month)
    else:
        projected = count

    projected_pct = (projected / limit * 100) if limit > 0 else 0

    exhaustion_date = None
    recommendation = None
    if daily_rate > 0 and limit > 0:
        days_to_exhaust = (limit - count) / daily_rate
        if days_to_exhaust < (days_in_month - day_of_month):
            exhaust_dt = now + timedelta(days=days_to_exhaust)
            exhaustion_date = exhaust_dt.strftime("%Y-%m-%d")
            recommendation = "reduce_polling_frequency"

    return {
        "data": {
            "currentMonth": month_key,
            "projectedRequests": projected,
            "projectedPercentage": round(projected_pct, 1),
            "projectedExhaustionDate": exhaustion_date,
            "recommendation": recommendation,
        }
    }


# ──────────────────────────── Degradation ────────────────────────────


@admin_router.get("/degradation")
async def get_degradation_status(
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_STATE_TABLE", "collection_state")
    item = table.get_item(
        Key={"pk": "collection_state", "sk": "degradation"}
    ).get("Item", {})

    return {
        "data": {
            "active": item.get("active", False),
            "activatedAt": item.get("activated_at"),
            "activatedBy": item.get("activated_by"),
            "reason": item.get("reason"),
            "autoActivated": item.get("auto_activated", False),
            "affectedLeagues": item.get("affected_leagues", []),
        }
    }


@admin_router.post("/degradation/activate")
async def activate_degraded_mode(
    body: DegradationActivateRequest,
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_STATE_TABLE", "collection_state")
    admin_id = _auth.get("sub", "unknown")
    now = datetime.now(UTC).isoformat()

    table.update_item(
        Key={"pk": "collection_state", "sk": "degradation"},
        UpdateExpression=(
            "SET active = :true, activated_at = :now, "
            "activated_by = :admin, reason = :reason, "
            "auto_activated = :false"
        ),
        ExpressionAttributeValues={
            ":true": True,
            ":now": now,
            ":admin": admin_id,
            ":reason": body.reason,
            ":false": False,
        },
    )

    return await get_degradation_status(_auth=_auth)


@admin_router.post("/degradation/deactivate")
async def deactivate_degraded_mode(
    _auth: dict = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    table = _get_table("VB_STATE_TABLE", "collection_state")

    table.update_item(
        Key={"pk": "collection_state", "sk": "degradation"},
        UpdateExpression=(
            "SET active = :false, reason = :null, "
            "activated_by = :null, auto_activated = :false"
        ),
        ExpressionAttributeValues={
            ":false": False,
            ":null": None,
        },
    )

    return await get_degradation_status(_auth=_auth)


# ──────────────────────────── Elite Snapshots ────────────────────────────


@elite_router.get("/snapshots")
async def list_snapshots(
    event_id: str | None = Query(None, alias="eventId"),
    league_id: str | None = Query(None, alias="leagueId"),
    market_type: MarketTypeEnum | None = Query(None, alias="marketType"),
    bookmaker_id: str | None = Query(None, alias="bookmakerId"),
    from_dt: str | None = Query(None, alias="from"),
    to_dt: str | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=1000),
    cursor: str | None = None,
    _api_key: str = Depends(verify_elite_api_key),
) -> dict[str, Any]:
    if not event_id and not league_id:
        raise HTTPException(
            status_code=400,
            detail="Ao menos um filtro entre eventId ou leagueId é obrigatório",
        )

    table = _get_table("VB_SNAPSHOTS_TABLE", "odds_snapshots")

    if event_id:
        response = table.query(
            KeyConditionExpression="event_id = :eid",
            ExpressionAttributeValues={":eid": event_id},
            Limit=limit,
            ScanIndexForward=False,
        )
    else:
        response = table.scan(Limit=limit)

    items = response.get("Items", [])
    last_key = response.get("LastEvaluatedKey")

    return {
        "data": items,
        "pagination": {
            "limit": limit,
            "cursor": str(last_key) if last_key else None,
            "hasMore": last_key is not None,
        },
    }
