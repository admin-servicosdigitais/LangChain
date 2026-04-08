from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3


@lru_cache(maxsize=1)
def get_dynamodb_resource(
    region_name: str = "us-east-1",
    endpoint_url: str | None = None,
) -> Any:
    kwargs: dict[str, str] = {"region_name": region_name}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.resource("dynamodb", **kwargs)


@lru_cache(maxsize=1)
def get_sqs_client(
    region_name: str = "us-east-1",
    endpoint_url: str | None = None,
) -> Any:
    kwargs: dict[str, str] = {"region_name": region_name}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("sqs", **kwargs)


@lru_cache(maxsize=1)
def get_cloudwatch_client(
    region_name: str = "us-east-1",
) -> Any:
    return boto3.client("cloudwatch", region_name=region_name)
