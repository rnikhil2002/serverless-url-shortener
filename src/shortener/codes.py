import re
import secrets
import string

ALPHABET = string.ascii_letters + string.digits  # base62
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
RESERVED = {"api", "stats", "admin", "health", "links", "dashboard"}


def random_code(length: int = 7) -> str:
    """62^7 is about 3.5 trillion codes, so collisions are rare and we just retry."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def is_valid_alias(alias: str) -> bool:
    return bool(ALIAS_RE.match(alias)) and alias.lower() not in RESERVED
