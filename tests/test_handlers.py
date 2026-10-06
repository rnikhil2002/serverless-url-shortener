import json
import time

from shortener import handlers
from shortener.analytics import aggregate
from conftest import api_event, drain


def body(res):
    return json.loads(res["body"])


def test_create_returns_short_url(aws):
    res = handlers.create_link(api_event({"url": "https://example.com"}))
    assert res["statusCode"] == 201
    data = body(res)
    assert data["short_url"] == f"https://sho.rt/{data['code']}"
    assert len(data["code"]) == 7


def test_custom_alias_and_duplicate(aws):
    first = handlers.create_link(api_event({"url": "https://example.com", "alias": "launch"}))
    assert body(first)["code"] == "launch"
    again = handlers.create_link(api_event({"url": "https://other.com", "alias": "launch"}))
    assert again["statusCode"] == 409


def test_create_rejects_bad_json_and_bad_url(aws):
    bad_json = api_event()
    bad_json["body"] = "{not json"
    assert handlers.create_link(bad_json)["statusCode"] == 400
    assert handlers.create_link(api_event({"url": "nope"}))["statusCode"] == 400


def test_redirect_and_queue_click(aws):
    code = body(handlers.create_link(api_event({"url": "https://example.com/page"})))["code"]
    res = handlers.redirect_link(api_event(code=code))
    assert res["statusCode"] == 302
    assert res["headers"]["Location"] == "https://example.com/page"
    assert len(drain(aws["sqs"], aws["queue_url"])) == 1


def test_redirect_unknown_code(aws):
    assert handlers.redirect_link(api_event(code="missing"))["statusCode"] == 404


def test_expired_link_returns_410(aws):
    aws["deps"].repo.create("old", "https://example.com", "key:user-1", int(time.time()) - 10)
    assert handlers.redirect_link(api_event(code="old"))["statusCode"] == 410


def test_redirect_still_works_if_analytics_fails(aws):
    code = body(handlers.create_link(api_event({"url": "https://example.com"})))["code"]
    aws["deps"].clicks.queue_url = "https://sqs.us-east-1.amazonaws.com/000000000000/does-not-exist"
    assert handlers.redirect_link(api_event(code=code))["statusCode"] == 302


def test_rate_limit_per_caller(aws):
    for _ in range(5):
        assert handlers.create_link(api_event({"url": "https://example.com"}))["statusCode"] == 201
    assert handlers.create_link(api_event({"url": "https://example.com"}))["statusCode"] == 429
    # a different user still gets through
    assert handlers.create_link(api_event({"url": "https://example.com"}, api_key="user-2"))["statusCode"] == 201


def test_rate_limit_falls_back_to_ip(aws):
    for _ in range(5):
        handlers.create_link(api_event({"url": "https://example.com"}, api_key=None, ip="9.9.9.9"))
    res = handlers.create_link(api_event({"url": "https://example.com"}, api_key=None, ip="9.9.9.9"))
    assert res["statusCode"] == 429


def test_rate_limit_resets_next_minute(aws):
    limiter = aws["deps"].limiter
    now = 1_700_000_000
    for _ in range(5):
        assert limiter.allow("x", now)
    assert not limiter.allow("x", now)
    assert limiter.allow("x", now + 60)


def test_click_pipeline_updates_stats(aws):
    code = body(handlers.create_link(api_event({"url": "https://example.com"})))["code"]
    for _ in range(4):
        handlers.redirect_link(api_event(code=code, api_key="visitor"))
    records = drain(aws["sqs"], aws["queue_url"])
    assert handlers.process_clicks({"Records": records})["processed"] == 4

    stats = body(handlers.link_stats(api_event(code=code)))
    assert stats["total_clicks"] == 4
    assert stats["daily"][0]["count"] == 4


def test_aggregate_skips_bad_messages():
    counts = aggregate([
        {"body": json.dumps({"code": "a", "day": "2026-10-01"})},
        {"body": json.dumps({"code": "a", "day": "2026-10-01"})},
        {"body": "garbage"},
        {"body": json.dumps({"code": "b"})},
    ])
    assert counts == {("a", "2026-10-01"): 2}


def test_stats_and_delete_are_owner_only(aws):
    code = body(handlers.create_link(api_event({"url": "https://example.com"})))["code"]
    assert handlers.link_stats(api_event(code=code, api_key="someone-else"))["statusCode"] == 404
    assert handlers.delete_link(api_event(code=code, api_key="someone-else"))["statusCode"] == 404
    assert handlers.delete_link(api_event(code=code))["statusCode"] == 204
    assert handlers.redirect_link(api_event(code=code))["statusCode"] == 404
