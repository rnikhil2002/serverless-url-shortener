import json

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "content-type,x-api-key"}


def json_response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json", **CORS}, "body": json.dumps(body)}


def error(status: int, message: str) -> dict:
    return json_response(status, {"error": message})


def redirect(location: str) -> dict:
    # 302 instead of 301 so browsers don't cache the redirect and every click is counted.
    return {"statusCode": 302, "headers": {"Location": location, "Cache-Control": "no-store"}, "body": ""}
