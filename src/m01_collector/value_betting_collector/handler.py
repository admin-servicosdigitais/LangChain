from __future__ import annotations

import asyncio
import time
from typing import Any

import sentry_sdk
from value_betting_shared.aws_clients import (
    get_cloudwatch_client,
    get_dynamodb_resource,
    get_sqs_client,
)
from value_betting_shared.logging import set_correlation_id, setup_logger
from value_betting_shared.metrics import put_metric
from value_betting_shared.models.enums import MarketTypeEnum

from value_betting_collector.config import CollectorSettings
from value_betting_collector.orchestrator import CollectionOrchestrator
from value_betting_collector.services.degradation import DegradationManager
from value_betting_collector.services.movement_detector import MovementDetector
from value_betting_collector.services.quality_monitor import QualityMonitor
from value_betting_collector.services.quota_tracker import QuotaTracker
from value_betting_collector.services.snapshot_writer import SnapshotWriter
from value_betting_collector.sources.api_football import ApiFootballClient
from value_betting_collector.sources.betfair import BetfairClient
from value_betting_collector.sources.odds_api import TheOddsApiClient

logger = setup_logger("m01_collector")


def _init_sentry(dsn: str) -> None:
    if dsn:
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.1)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return asyncio.get_event_loop().run_until_complete(_async_handler(event, context))


async def _async_handler(
    event: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    start = time.monotonic()
    settings = CollectorSettings()
    _init_sentry(settings.sentry_dsn)

    request_id = getattr(context, "aws_request_id", "local")
    set_correlation_id(request_id)

    dynamodb = get_dynamodb_resource(
        region_name=settings.aws_region,
        endpoint_url=settings.dynamodb_endpoint_url,
    )
    sqs = get_sqs_client(
        region_name=settings.aws_region,
        endpoint_url=settings.sqs_endpoint_url,
    )
    cw = get_cloudwatch_client(region_name=settings.aws_region)

    snapshots_table = dynamodb.Table(settings.snapshots_table)
    state_table = dynamodb.Table(settings.collection_state_table)
    quota_table = dynamodb.Table(settings.quota_table)

    degradation = DegradationManager(
        table=state_table,
        max_consecutive_failures=settings.max_consecutive_failures,
    )
    status = degradation.get_status()
    if status.active:
        logger.warning("Pipeline in degraded mode, skipping collection")
        return {"statusCode": 200, "body": "degraded_mode_active"}

    odds_client = TheOddsApiClient(
        api_key=settings.odds_api_key,
        base_url=settings.odds_api_base_url,
    )
    betfair_client = BetfairClient(
        app_key=settings.betfair_app_key,
        session_token=settings.betfair_session_token,
        base_url=settings.betfair_base_url,
        max_rps=settings.betfair_max_rps,
    )
    football_client = ApiFootballClient(
        api_key=settings.api_football_key,
        base_url=settings.api_football_base_url,
    )

    writer = SnapshotWriter(table=snapshots_table)
    detector = MovementDetector(
        sqs_client=sqs,
        queue_url=settings.movement_queue_url,
        threshold_pct=settings.movement_threshold_pct,
    )
    quota = QuotaTracker(
        table=quota_table,
        monthly_limit=settings.odds_api_monthly_limit,
        warning_pct=settings.quota_warning_pct,
        critical_pct=settings.quota_critical_pct,
    )
    quality = QualityMonitor(
        pinnacle_coverage_min_pct=settings.pinnacle_coverage_min_pct,
        volatility_threshold_pct=settings.pinnacle_volatility_threshold_pct,
        unreliable_coverage_pct=settings.bookmaker_unreliable_coverage_pct,
        unreliable_consecutive=settings.bookmaker_unreliable_consecutive,
    )

    orchestrator = CollectionOrchestrator(
        settings=settings,
        snapshot_writer=writer,
        movement_detector=detector,
        quality_monitor=quality,
    )

    sport = event.get("sport", "soccer")
    leagues = event.get("leagues", [])
    market_types = [MarketTypeEnum(m) for m in event.get("market_types", ["1x2"])]

    try:
        fetch_result = await odds_client.fetch_odds(sport, leagues, market_types)

        event_ids = list({r.event_id for r in fetch_result.odds})

        betfair_task = betfair_client.fetch_exchange_data(event_ids)
        football_task = football_client.fetch_match_context(event_ids)
        betfair_data, match_contexts = await asyncio.gather(
            betfair_task, football_task, return_exceptions=True,
        )

        if isinstance(betfair_data, BaseException):
            logger.warning("Betfair enrichment failed: %s", betfair_data)
            betfair_data = []
        if isinstance(match_contexts, BaseException):
            logger.warning("API-Football enrichment failed: %s", match_contexts)
            match_contexts = []

        result = await orchestrator.process_collection(
            fetch_result=fetch_result,
            betfair_data=betfair_data,
            match_contexts=match_contexts,
        )

        quota.increment(result.requests_used)
        degradation.record_success()

        duration_ms = (time.monotonic() - start) * 1000
        put_metric(
            cw,
            "M01/CollectionCycleDuration",
            duration_ms,
            dimensions={"Sport": sport},
        )

        if duration_ms > settings.max_cycle_duration_ms:
            logger.warning("Cycle exceeded budget: %.0fms", duration_ms)

        logger.info(
            "Collection complete",
            extra={
                "extra_data": {
                    "event_type": "COLLECTION_COMPLETE",
                    "snapshots_written": result.snapshots_written,
                    "movements_published": result.movements_published,
                    "requests_used": result.requests_used,
                    "duration_ms": round(duration_ms),
                    "errors": result.errors,
                }
            },
        )

        return {
            "statusCode": 200,
            "body": {
                "snapshots": result.snapshots_written,
                "movements": result.movements_published,
                "duration_ms": round(duration_ms),
            },
        }

    except Exception as e:
        degradation.record_failure()
        logger.error("Collection failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return {"statusCode": 500, "body": str(e)}

    finally:
        await odds_client.close()
        await betfair_client.close()
        await football_client.close()
