"""Run the shortener on your laptop with no AWS account.

Uses moto to fake DynamoDB and SQS in memory, and a tiny HTTP server that turns
requests into the same events API Gateway sends to Lambda.

    pip install -r requirements-dev.txt
    python scripts/local_server.py
    curl -X POST localhost:8000/links -H 'x-api-key: me' -d '{"url":"https://example.com"}'
"""
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")

import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

from conftest import make_tables  # noqa: E402
from shortener import handlers  # noqa: E402

ROUTES = [
    ("POST", re.compile(r"^/links$"), handlers.create_link),
    ("GET", re.compile(r"^/links/(?P<code>[^/]+)/stats$"), handlers.link_stats),
    ("DELETE", re.compile(r"^/links/(?P<code>[^/]+)$"), handlers.delete_link),
    ("GET", re.compile(r"^/(?P<code>[A-Za-z0-9_-]+)$"), handlers.redirect_link),
]


class Handler(BaseHTTPRequestHandler):
    def _dispatch(self, method):
        if method == "GET" and self.path in ("/", "/dashboard"):
            html = (ROOT / "dashboard" / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html)
            return
        for m, pattern, fn in ROUTES:
            match = pattern.match(self.path)
            if m == method and match:
                length = int(self.headers.get("Content-Length") or 0)
                event = {
                    "headers": dict(self.headers),
                    "requestContext": {"http": {"sourceIp": self.client_address[0]}},
                    "pathParameters": match.groupdict() or None,
                    "body": self.rfile.read(length).decode() if length else None,
                }
                res = fn(event)
                self.send_response(res["statusCode"])
                for k, v in (res.get("headers") or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write((res.get("body") or "").encode())
                return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type,x-api-key")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.end_headers()


def click_worker(sqs, queue_url):
    """Stands in for the SQS -> Lambda trigger."""
    while True:
        msgs = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get("Messages", [])
        if msgs:
            handlers.process_clicks({"Records": [{"body": m["Body"]} for m in msgs]})
            for m in msgs:
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=m["ReceiptHandle"])
        else:
            time.sleep(1)


def main():
    with mock_aws():
        make_tables(boto3.resource("dynamodb"))
        sqs = boto3.client("sqs")
        queue_url = sqs.create_queue(QueueName="clicks")["QueueUrl"]
        os.environ["CLICKS_QUEUE_URL"] = queue_url
        os.environ.setdefault("BASE_URL", "http://localhost:8000")
        handlers.set_deps(None)
        threading.Thread(target=click_worker, args=(sqs, queue_url), daemon=True).start()
        print("Shortener running at http://localhost:8000 (dashboard at /)")
        ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()


if __name__ == "__main__":
    main()
