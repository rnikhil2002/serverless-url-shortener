from datetime import datetime, timezone
from urllib.parse import urlparse

from .codes import is_valid_alias

MAX_URL_LENGTH = 2048
MAX_EXPIRY_DAYS = 365


class ValidationError(Exception):
    pass


def validate_create(body: dict) -> dict:
    url = (body.get("url") or "").strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise ValidationError("url is required and must be under 2048 characters")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValidationError("url must start with http:// or https://")

    alias = body.get("alias")
    if alias is not None and not is_valid_alias(alias):
        raise ValidationError("alias must be 3-32 letters, numbers, - or _, and not a reserved word")

    expires_in_days = body.get("expires_in_days")
    expires_at = None
    if expires_in_days is not None:
        if not isinstance(expires_in_days, int) or not 1 <= expires_in_days <= MAX_EXPIRY_DAYS:
            raise ValidationError("expires_in_days must be a whole number between 1 and 365")
        expires_at = int(datetime.now(timezone.utc).timestamp()) + expires_in_days * 86400

    return {"url": url, "alias": alias, "expires_at": expires_at}
