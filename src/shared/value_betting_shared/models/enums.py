from enum import StrEnum


class SportEnum(StrEnum):
    FOOTBALL = "football"
    TENNIS = "tennis"
    BASKETBALL = "basketball"
    BASEBALL = "baseball"


class TierEnum(StrEnum):
    FREE = "free"
    PRO = "pro"
    ELITE = "elite"


class MarketTypeEnum(StrEnum):
    ONE_X_TWO = "1x2"
    OVER_UNDER_2_5 = "over_under_2_5"
    OVER_UNDER_3_5 = "over_under_3_5"
    ASIAN_HANDICAP = "asian_handicap"
    BTTS = "btts"


class OddsSourceEnum(StrEnum):
    THE_ODDS_API = "the_odds_api"
    BETFAIR = "betfair"


class MatchStatusEnum(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class ComponentNameEnum(StrEnum):
    THE_ODDS_API = "the_odds_api"
    BETFAIR = "betfair"
    API_FOOTBALL = "api_football"
    DYNAMODB = "dynamodb"
    SQS = "sqs"


class ComponentStatusEnum(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class CollectionStatusEnum(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class QualityAlertTypeEnum(StrEnum):
    PINNACLE_COVERAGE_LOW = "pinnacle_coverage_low"
    HIGH_VOLATILITY = "high_volatility"
    BOOKMAKER_UNRELIABLE = "bookmaker_unreliable"
    ODDS_ANOMALY = "odds_anomaly"


class SeverityEnum(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertLevelEnum(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


class QuotaRecommendationEnum(StrEnum):
    NONE = "none"
    REDUCE_POLLING_FREQUENCY = "reduce_polling_frequency"
    DISABLE_LOW_PRIORITY_LEAGUES = "disable_low_priority_leagues"
