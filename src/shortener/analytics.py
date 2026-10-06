import json
from collections import Counter

import boto3

from .repository import LinkRepository


class ClickPublisher:
    """Sends click events to SQS so the redirect never waits on analytics writes."""

    def __init__(self, queue_url: str, sqs=None) -> None:
        self.queue_url = queue_url
        self.sqs = sqs or boto3.client("sqs")

    def publish(self, code: str, day: str) -> None:
        if not self.queue_url:
            return
        self.sqs.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps({"code": code, "day": day}))


def aggregate(records: list[dict]) -> Counter:
    """Group a batch of SQS messages into (code, day) -> count so we write once per pair."""
    counts: Counter = Counter()
    for r in records:
        try:
            body = json.loads(r["body"])
            counts[(body["code"], body["day"])] += 1
        except (KeyError, ValueError, TypeError):
            continue  # skip malformed messages instead of failing the whole batch
    return counts


def consume(records: list[dict], repo: LinkRepository) -> int:
    counts = aggregate(records)
    for (code, day), n in counts.items():
        repo.record_clicks(code, day, n)
    return sum(counts.values())
