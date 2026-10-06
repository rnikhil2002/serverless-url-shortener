import time
from datetime import datetime, timezone
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


class AlreadyExists(Exception):
    pass


class LinkRepository:
    """DynamoDB access for links and daily click counts.

    links:        pk = code
    clicks_daily: pk = code, sk = day (YYYY-MM-DD), count
    """

    def __init__(self, links_table: str, clicks_table: str, dynamodb=None) -> None:
        dynamodb = dynamodb or boto3.resource("dynamodb")
        self.links = dynamodb.Table(links_table)
        self.clicks = dynamodb.Table(clicks_table)

    def create(self, code: str, url: str, owner: str, expires_at: Optional[int]) -> dict:
        item = {"code": code, "url": url, "owner": owner, "created_at": int(time.time()), "clicks": 0}
        if expires_at:
            item["expires_at"] = expires_at  # also used as the DynamoDB TTL attribute
        try:
            # Conditional put: never overwrite an existing code or alias.
            self.links.put_item(Item=item, ConditionExpression="attribute_not_exists(code)")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise AlreadyExists(code) from e
            raise
        return item

    def get(self, code: str) -> Optional[dict]:
        return self.links.get_item(Key={"code": code}).get("Item")

    def delete(self, code: str, owner: str) -> bool:
        try:
            self.links.delete_item(
                Key={"code": code},
                ConditionExpression="#o = :owner",
                ExpressionAttributeNames={"#o": "owner"},
                ExpressionAttributeValues={":owner": owner},
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def record_clicks(self, code: str, day: str, count: int) -> None:
        """Atomic counters, so many consumers can update the same day at once."""
        self.clicks.update_item(
            Key={"code": code, "day": day},
            UpdateExpression="ADD #c :n",
            ExpressionAttributeNames={"#c": "count"},
            ExpressionAttributeValues={":n": count},
        )
        try:
            self.links.update_item(
                Key={"code": code},
                UpdateExpression="ADD clicks :n",
                ConditionExpression="attribute_exists(code)",
                ExpressionAttributeValues={":n": count},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise  # link was deleted; daily history is still kept

    def daily_clicks(self, code: str, days: int = 30) -> list[dict]:
        res = self.clicks.query(KeyConditionExpression=Key("code").eq(code), ScanIndexForward=False, Limit=days)
        return [{"day": i["day"], "count": int(i["count"])} for i in reversed(res["Items"])]


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
