terraform {
  required_version = ">= 1.5"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = "url-shortener", env = var.env }
  }
}

locals {
  name = "url-shortener-${var.env}"
}

# ---------- Storage ----------

resource "aws_dynamodb_table" "links" {
  name         = "${local.name}-links"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "code"

  attribute {
    name = "code"
    type = "S"
  }

  # Expired links are removed automatically
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.env == "prod"
  }
}

resource "aws_dynamodb_table" "clicks_daily" {
  name         = "${local.name}-clicks-daily"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "code"
  range_key    = "day"

  attribute {
    name = "code"
    type = "S"
  }
  attribute {
    name = "day"
    type = "S"
  }
}

resource "aws_dynamodb_table" "rate_limits" {
  name         = "${local.name}-rate-limits"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "key"

  attribute {
    name = "key"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

# ---------- Click queue ----------

resource "aws_sqs_queue" "clicks_dlq" {
  name                      = "${local.name}-clicks-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "clicks" {
  name                       = "${local.name}-clicks"
  visibility_timeout_seconds = 60
  redrive_policy             = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.clicks_dlq.arn
    maxReceiveCount     = 5
  })
}
