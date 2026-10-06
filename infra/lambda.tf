data "archive_file" "code" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/build/shortener.zip"
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-lambda"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

# Least privilege: only the tables and queue this app uses.
resource "aws_iam_role_policy" "lambda" {
  role   = aws_iam_role.lambda.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query"]
        Resource = [
          aws_dynamodb_table.links.arn,
          aws_dynamodb_table.clicks_daily.arn,
          aws_dynamodb_table.rate_limits.arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.clicks.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      },
    ]
  })
}

locals {
  functions = {
    create   = { handler = "shortener.handlers.create_link", memory = 256 }
    redirect = { handler = "shortener.handlers.redirect_link", memory = 256 }
    stats    = { handler = "shortener.handlers.link_stats", memory = 256 }
    delete   = { handler = "shortener.handlers.delete_link", memory = 128 }
    clicks   = { handler = "shortener.handlers.process_clicks", memory = 256 }
  }
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = 14
}

resource "aws_lambda_function" "fn" {
  for_each         = local.functions
  function_name    = "${local.name}-${each.key}"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = each.value.handler
  memory_size      = each.value.memory
  timeout          = 10
  filename         = data.archive_file.code.output_path
  source_code_hash = data.archive_file.code.output_base64sha256

  environment {
    variables = {
      LINKS_TABLE           = aws_dynamodb_table.links.name
      CLICKS_TABLE          = aws_dynamodb_table.clicks_daily.name
      LIMITS_TABLE          = aws_dynamodb_table.rate_limits.name
      CLICKS_QUEUE_URL      = aws_sqs_queue.clicks.url
      BASE_URL              = var.base_url != "" ? var.base_url : aws_apigatewayv2_api.http.api_endpoint
      RATE_LIMIT_PER_MINUTE = tostring(var.rate_limit_per_minute)
    }
  }

  depends_on = [aws_cloudwatch_log_group.fn]
}

# Batches of up to 50 clicks are grouped and written as one counter update per link per day.
resource "aws_lambda_event_source_mapping" "clicks" {
  event_source_arn                   = aws_sqs_queue.clicks.arn
  function_name                      = aws_lambda_function.fn["clicks"].arn
  batch_size                         = 50
  maximum_batching_window_in_seconds = 5
}
