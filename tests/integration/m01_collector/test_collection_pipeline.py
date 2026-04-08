from __future__ import annotations

import os
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws
from value_betting_collector.services.movement_detector import MovementDetector
from value_betting_collector.services.snapshot_writer import SnapshotWriter
from value_betting_shared.models.enums import MarketTypeEnum, OddsSourceEnum
from value_betting_shared.models.odds import OddsSnapshot, PinnacleOdds


@pytest.fixture
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def dynamodb_table(aws_credentials):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="odds_snapshots",
            KeySchema=[
                {"AttributeName": "event_id", "KeyType": "HASH"},
                {"AttributeName": "sort_key", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "event_id", "AttributeType": "S"},
                {"AttributeName": "sort_key", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.meta.client.get_waiter("table_exists").wait(TableName="odds_snapshots")
        yield table


@pytest.fixture
def sqs_queue(aws_credentials):
    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue = sqs.create_queue(
            QueueName="odds-movement-events.fifo",
            Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "false"},
        )
        yield sqs, queue["QueueUrl"]


def _make_snapshot(event_id: str, home: float = 2.10, away: float = 3.60) -> OddsSnapshot:
    return OddsSnapshot(
        event_id=event_id,
        market_type=MarketTypeEnum.ONE_X_TWO,
        bookmaker_id="bet365",
        odds_home=home,
        odds_draw=3.40,
        odds_away=away,
        pinnacle_odds=PinnacleOdds(home=home, draw=3.40, away=away),
        collected_at=datetime(2026, 4, 7, 14, 0, 0, tzinfo=UTC),
        source=OddsSourceEnum.THE_ODDS_API,
    )


class TestSnapshotWriterIntegration:
    @pytest.mark.asyncio
    async def test_write_and_read_from_dynamodb(self, dynamodb_table):
        writer = SnapshotWriter(table=dynamodb_table)
        snapshots = [_make_snapshot(f"match_{i}") for i in range(5)]

        written = await writer.write_batch(snapshots)
        assert written == 5

        response = dynamodb_table.query(
            KeyConditionExpression="event_id = :eid",
            ExpressionAttributeValues={":eid": "match_0"},
        )
        assert len(response["Items"]) == 1
        item = response["Items"][0]
        assert item["market_type"] == "1x2"
        assert item["bookmaker_id"] == "bet365"


class TestMovementDetectorIntegration:
    @pytest.mark.asyncio
    async def test_publish_to_sqs(self, sqs_queue):
        sqs_client, queue_url = sqs_queue
        detector = MovementDetector(
            sqs_client=sqs_client,
            queue_url=queue_url,
            threshold_pct=2.0,
        )

        first = _make_snapshot("match_001", home=2.00, away=3.00)
        await detector.detect_and_publish([first])

        second = _make_snapshot("match_001", home=2.30, away=3.40)
        published = await detector.detect_and_publish([second])

        assert published == 1

        messages = sqs_client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
        )
        assert len(messages.get("Messages", [])) == 1
