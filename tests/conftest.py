import json
import os

import boto3
import pytest
from moto import mock_aws

from shortener import handlers
from shortener.analytics import ClickPublisher
from shortener.config import Config
from shortener.rate_limit import RateLimiter
from shortener.repository import LinkRepository

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")


def make_tables(ddb):
    ddb.create_table(
        TableName="links",
        KeySchema=[{"AttributeName": "code", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "code", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="clicks_daily",
        KeySchema=[{"AttributeName": "code", "KeyType": "HASH"}, {"AttributeName": "day", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "code", "AttributeType": "S"},
            {"AttributeName": "day", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="rate_limits",
        KeySchema=[{"AttributeName": "key", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "key", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def aws():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        sqs = boto3.client("sqs", region_name="us-east-1")
        make_tables(ddb)
        queue_url = sqs.create_queue(QueueName="clicks")["QueueUrl"]
        cfg = Config()
        cfg.clicks_queue_url = queue_url
        cfg.base_url = "https://sho.rt"
        cfg.rate_limit_per_minute = 5
        d = handlers.Deps(
            config=cfg,
            repo=LinkRepository("links", "clicks_daily", ddb),
            limiter=RateLimiter("rate_limits", cfg.rate_limit_per_minute, ddb),
            clicks=ClickPublisher(queue_url, sqs),
        )
        handlers.set_deps(d)
        yield {"deps": d, "sqs": sqs, "queue_url": queue_url, "ddb": ddb}
        handlers.set_deps(None)


def api_event(body=None, code=None, api_key="user-1", ip="1.2.3.4"):
    event = {
        "headers": {"x-api-key": api_key} if api_key else {},
        "requestContext": {"http": {"sourceIp": ip}},
        "body": json.dumps(body) if body is not None else None,
    }
    if code:
        event["pathParameters"] = {"code": code}
    return event


def drain(sqs, queue_url):
    """Pull every queued message, shaped like an SQS Lambda event."""
    records = []
    while True:
        msgs = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get("Messages", [])
        if not msgs:
            return records
        for m in msgs:
            records.append({"body": m["Body"]})
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=m["ReceiptHandle"])
