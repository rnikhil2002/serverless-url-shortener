"""Lambda entry points. API Gateway (HTTP API, payload v2) calls the first four, SQS calls the last."""
import json
import logging
import time
from dataclasses import dataclass

from .analytics import ClickPublisher, consume
from .codes import random_code
from .config import Config
from .rate_limit import RateLimiter
from .repository import AlreadyExists, LinkRepository, today
from .responses import error, json_response, redirect
from .validation import ValidationError, validate_create

log = logging.getLogger()
log.setLevel(logging.INFO)

MAX_CODE_ATTEMPTS = 5


@dataclass
class Deps:
    config: Config
    repo: LinkRepository
    limiter: RateLimiter
    clicks: ClickPublisher


_deps: Deps | None = None


def deps() -> Deps:
    """Created once per Lambda container and reused across warm invocations."""
    global _deps
    if _deps is None:
        cfg = Config()
        _deps = Deps(
            config=cfg,
            repo=LinkRepository(cfg.links_table, cfg.clicks_table),
            limiter=RateLimiter(cfg.limits_table, cfg.rate_limit_per_minute),
            clicks=ClickPublisher(cfg.clicks_queue_url),
        )
    return _deps


def set_deps(d: Deps | None) -> None:
    global _deps
    _deps = d


def caller_id(event: dict) -> str:
    """Per-user identity for ownership and rate limits: API key if sent, otherwise source IP."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if headers.get("x-api-key"):
        return f"key:{headers['x-api-key']}"
    ip = event.get("requestContext", {}).get("http", {}).get("sourceIp", "unknown")
    return f"ip:{ip}"


def log_event(**fields) -> None:
    log.info(json.dumps(fields))


def create_link(event: dict, _context=None) -> dict:
    d = deps()
    caller = caller_id(event)
    if not d.limiter.allow(caller):
        return error(429, "Too many requests, try again in a minute")
    try:
        body = json.loads(event.get("body") or "{}")
        data = validate_create(body)
    except (ValueError, ValidationError) as e:
        return error(400, str(e) if isinstance(e, ValidationError) else "Body must be valid JSON")

    if data["alias"]:
        try:
            item = d.repo.create(data["alias"], data["url"], caller, data["expires_at"])
        except AlreadyExists:
            return error(409, "That alias is already taken")
    else:
        item = None
        for _ in range(MAX_CODE_ATTEMPTS):
            try:
                item = d.repo.create(random_code(d.config.code_length), data["url"], caller, data["expires_at"])
                break
            except AlreadyExists:
                continue
        if item is None:
            return error(503, "Could not generate a short code, please retry")

    log_event(action="create", code=item["code"], caller=caller)
    return json_response(
        201,
        {
            "code": item["code"],
            "short_url": f"{d.config.base_url}/{item['code']}",
            "url": item["url"],
            "expires_at": item.get("expires_at"),
        },
    )


def redirect_link(event: dict, _context=None) -> dict:
    d = deps()
    code = (event.get("pathParameters") or {}).get("code", "")
    item = d.repo.get(code)
    if not item:
        return error(404, "Short link not found")
    # DynamoDB TTL can take a while to delete expired items, so check it here too.
    if item.get("expires_at") and int(item["expires_at"]) < time.time():
        return error(410, "This link has expired")
    try:
        d.clicks.publish(code, today())
    except Exception:  # analytics should never break a redirect
        log.exception("failed to publish click")
    return redirect(item["url"])


def link_stats(event: dict, _context=None) -> dict:
    d = deps()
    code = (event.get("pathParameters") or {}).get("code", "")
    item = d.repo.get(code)
    if not item or item["owner"] != caller_id(event):
        return error(404, "Short link not found")
    return json_response(
        200,
        {
            "code": code,
            "url": item["url"],
            "total_clicks": int(item.get("clicks", 0)),
            "daily": d.repo.daily_clicks(code),
            "expires_at": item.get("expires_at"),
        },
    )


def delete_link(event: dict, _context=None) -> dict:
    d = deps()
    code = (event.get("pathParameters") or {}).get("code", "")
    if not d.repo.delete(code, caller_id(event)):
        return error(404, "Short link not found")
    log_event(action="delete", code=code)
    return {"statusCode": 204, "body": ""}


def process_clicks(event: dict, _context=None) -> dict:
    d = deps()
    processed = consume(event.get("Records", []), d.repo)
    log_event(action="clicks", processed=processed)
    return {"processed": processed}
