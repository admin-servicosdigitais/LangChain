from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_cloudwatch import CloudWatchClient

NAMESPACE = "ValueBetting"


def put_metric(
    client: CloudWatchClient,
    metric_name: str,
    value: float,
    unit: str = "Milliseconds",
    dimensions: dict[str, str] | None = None,
) -> None:
    metric_data: dict = {
        "MetricName": metric_name,
        "Value": value,
        "Unit": unit,
        "Timestamp": datetime.now(UTC),
    }
    if dimensions:
        metric_data["Dimensions"] = [
            {"Name": k, "Value": v} for k, v in dimensions.items()
        ]
    client.put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[metric_data],
    )
