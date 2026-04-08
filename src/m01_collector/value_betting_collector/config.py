from __future__ import annotations

from pydantic_settings import BaseSettings


class CollectorSettings(BaseSettings):
    model_config = {"env_prefix": "VB_"}

    # AWS
    aws_region: str = "us-east-1"
    dynamodb_endpoint_url: str | None = None
    sqs_endpoint_url: str | None = None

    # DynamoDB tables
    snapshots_table: str = "odds_snapshots"
    quota_table: str = "api_quota"
    polling_overrides_table: str = "polling_overrides"
    collection_state_table: str = "collection_state"

    # SQS
    movement_queue_url: str = ""

    # The Odds API
    odds_api_key: str = ""
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"
    odds_api_monthly_limit: int = 500_000

    # Betfair
    betfair_app_key: str = ""
    betfair_session_token: str = ""
    betfair_base_url: str = "https://api.betfair.com/exchange"
    betfair_max_rps: int = 3

    # API-Football
    api_football_key: str = ""
    api_football_base_url: str = "https://v3.football.api-sports.io"

    # Polling intervals (defaults from RF-COL-001)
    polling_interval_24h_sec: int = 30
    polling_interval_72h_sec: int = 300
    polling_interval_beyond_72h_sec: int = 1800

    # Thresholds
    movement_threshold_pct: float = 2.0
    pinnacle_volatility_threshold_pct: float = 15.0
    low_liquidity_threshold_usd: float = 10_000.0
    bookmaker_unreliable_coverage_pct: float = 10.0
    bookmaker_unreliable_consecutive: int = 3
    pinnacle_coverage_min_pct: float = 50.0
    quota_warning_pct: float = 80.0
    quota_critical_pct: float = 95.0
    max_consecutive_failures: int = 3

    # Sentry
    sentry_dsn: str = ""

    # Cycle
    max_cycle_duration_ms: int = 25_000
