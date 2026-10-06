import pytest

from shortener.codes import ALPHABET, is_valid_alias, random_code
from shortener.validation import ValidationError, validate_create


def test_random_code_uses_base62_and_length():
    code = random_code(9)
    assert len(code) == 9
    assert set(code) <= set(ALPHABET)


def test_random_codes_are_unique_enough():
    assert len({random_code() for _ in range(2000)}) == 2000


@pytest.mark.parametrize("alias,ok", [
    ("my-link", True), ("abc", True), ("ab", False), ("has space", False),
    ("x" * 33, False), ("api", False), ("Stats", False),
])
def test_alias_rules(alias, ok):
    assert is_valid_alias(alias) is ok


def test_accepts_valid_url():
    assert validate_create({"url": "https://example.com/a?b=1"})["url"] == "https://example.com/a?b=1"


@pytest.mark.parametrize("url", ["", "example.com", "ftp://example.com", "javascript:alert(1)", "https://" + "a" * 2050])
def test_rejects_bad_urls(url):
    with pytest.raises(ValidationError):
        validate_create({"url": url})


@pytest.mark.parametrize("days", [0, 366, "7", 1.5])
def test_rejects_bad_expiry(days):
    with pytest.raises(ValidationError):
        validate_create({"url": "https://example.com", "expires_in_days": days})


def test_expiry_becomes_timestamp():
    out = validate_create({"url": "https://example.com", "expires_in_days": 1})
    assert out["expires_at"] > 0
