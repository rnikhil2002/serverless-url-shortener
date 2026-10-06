# Serverless URL Shortener with Click Analytics

A URL shortening service built on AWS serverless pieces: **Lambda (Python)**, **API Gateway**, **DynamoDB** and **SQS**, with all infrastructure defined in **Terraform**.

## Features

- Short codes (random base62) or custom aliases like `/launch`
- Optional link expiry (expired links return 410, and DynamoDB TTL cleans them up)
- Per-user rate limiting shared across every Lambda instance (keyed by API key, or by IP if no key is sent)
- Click tracking that never slows down the redirect: the redirect drops a message on SQS and returns right away, and a separate Lambda counts clicks in batches
- Daily click stats per link, only visible to the link's owner
- Small dashboard page to create links and see daily clicks

## How it works

```
             ┌──────────────┐   302    ┌────────┐
GET /{code} ─▶ redirect λ    ├─────────▶ target │
             └──────┬───────┘          └────────┘
                    │ click event
               ┌────▼────┐   batches of 50   ┌───────────┐
               │   SQS   ├──────────────────▶ clicks λ   │──▶ DynamoDB clicks_daily
               └────┬────┘                   └───────────┘
                    └── DLQ after 5 failed tries (with an alarm)

POST /links  ─▶ create λ ─▶ rate limit check ─▶ DynamoDB links (conditional put)
GET  /links/{code}/stats ─▶ stats λ
DELETE /links/{code}     ─▶ delete λ (owner only)
```

Some decisions worth calling out:

- **302, not 301.** Browsers cache 301s, so repeat clicks would never reach the API and wouldn't be counted.
- **Conditional writes everywhere.** New codes use `attribute_not_exists`, so a collision or a taken alias can never overwrite someone else's link. The rate limiter increments and checks the limit in one conditional update, so parallel requests can't slip past it.
- **Batching clicks.** The consumer groups a batch by `(code, day)` and writes one atomic counter update per group instead of one per click.
- **Analytics can't break redirects.** If SQS is down, the redirect still works and the error is logged.

## API

| Method | Path | Description |
|---|---|---|
| POST | `/links` | Body: `{"url": "...", "alias": "optional", "expires_in_days": 30}` |
| GET | `/{code}` | Redirects to the original URL |
| GET | `/links/{code}/stats` | Total and daily clicks (owner only) |
| DELETE | `/links/{code}` | Delete a link (owner only) |

Send an `x-api-key` header to identify yourself.

## Run it locally (no AWS account needed)

```bash
pip install -r requirements-dev.txt
python scripts/local_server.py
```

This fakes DynamoDB and SQS in memory with moto. Then:

```bash
curl -X POST localhost:8000/links -H 'x-api-key: me' -d '{"url":"https://example.com","alias":"demo"}'
curl -i localhost:8000/demo
curl localhost:8000/links/demo/stats -H 'x-api-key: me'
```

Or open http://localhost:8000 for the dashboard.

## Tests

```bash
pytest -q
```

Covers validation, alias rules, create/redirect/expiry, rate limiting (per user, per IP, and window reset), the full click pipeline from redirect to SQS to stats, malformed queue messages, and owner-only access.

## Deploy to AWS

```bash
cd infra
terraform init
terraform apply -var-file=dev.tfvars     # or prod.tfvars
```

Creates the three DynamoDB tables (on-demand billing, TTL enabled), the SQS queue and dead-letter queue, five Lambda functions (arm64, Python 3.12), the HTTP API with routes and throttling, least-privilege IAM, log groups with 14-day retention, and CloudWatch alarms for Lambda errors, redirect p95 latency and messages stuck in the DLQ. Everything is pay-per-request, so a low-traffic dev environment costs very little.

## Project structure

```
src/shortener/
  handlers.py     Lambda entry points
  repository.py   DynamoDB access (links + daily clicks)
  rate_limit.py   Fixed-window rate limiter on DynamoDB
  analytics.py    SQS publisher and batch consumer
  validation.py   Input checks
  codes.py        Short code generation and alias rules
tests/
infra/            Terraform
scripts/local_server.py
dashboard/index.html
```
