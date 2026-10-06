import time

import boto3
from botocore.exceptions import ClientError


class RateLimiter:
    """Fixed-window limiter stored in DynamoDB, shared by every Lambda instance.

    Each caller gets one counter per minute. The increment and the limit check happen
    in a single conditional update, so concurrent requests can't sneak past the limit.
    Old windows clean themselves up through DynamoDB TTL.
    """

    def __init__(self, table: str, limit_per_minute: int, dynamodb=None) -> None:
        dynamodb = dynamodb or boto3.resource("dynamodb")
        self.table = dynamodb.Table(table)
        self.limit = limit_per_minute

    def allow(self, caller: str, now: float | None = None) -> bool:
        now = now or time.time()
        window = int(now // 60)
        try:
            self.table.update_item(
                Key={"key": f"{caller}#{window}"},
                UpdateExpression="ADD hits :one SET expires_at = :exp",
                ConditionExpression="attribute_not_exists(hits) OR hits < :limit",
                ExpressionAttributeValues={":one": 1, ":limit": self.limit, ":exp": (window + 2) * 60},
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
