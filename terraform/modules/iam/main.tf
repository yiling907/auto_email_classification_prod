# IAM module - Roles and policies for Lambda and Step Functions

locals {
  resource_prefix = "${var.project_name}-${var.environment}"
}

data "aws_caller_identity" "current" {}

# Lambda execution role
resource "aws_iam_role" "lambda_execution" {
  name = "${local.resource_prefix}-lambda-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(var.tags, { Name = "${local.resource_prefix}-lambda-execution" })
}

# Lambda basic execution policy (CloudWatch Logs)
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Lambda policy for S3 access
resource "aws_iam_role_policy" "lambda_s3" {
  name = "${local.resource_prefix}-lambda-s3"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          var.email_bucket_arn,
          "${var.email_bucket_arn}/*",
          var.knowledge_base_bucket_arn,
          "${var.knowledge_base_bucket_arn}/*",
          var.logs_bucket_arn,
          "${var.logs_bucket_arn}/*"
        ]
      }
    ]
  })
}

# Lambda policy for DynamoDB access
resource "aws_iam_role_policy" "lambda_dynamodb" {
  name = "${local.resource_prefix}-lambda-dynamodb"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:BatchGetItem",
          "dynamodb:BatchWriteItem"
        ]
        Resource = [
          var.email_table_arn,
          "${var.email_table_arn}/index/*",
          var.model_metrics_table_arn,
          "${var.model_metrics_table_arn}/index/*",
          var.embeddings_table_arn,
          "${var.embeddings_table_arn}/index/*"
        ]
      }
    ]
  })
}

# Lambda policy for Bedrock access
resource "aws_iam_role_policy" "lambda_bedrock" {
  name = "${local.resource_prefix}-lambda-bedrock"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-text-lite-v1",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v1",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/meta.llama3-8b-instruct-v1:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/mistral.mistral-7b-instruct-v0:2"
        ]
      }
    ]
  })
}

# Step Functions execution role
resource "aws_iam_role" "step_functions" {
  name = "${local.resource_prefix}-step-functions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(var.tags, { Name = "${local.resource_prefix}-step-functions" })
}

# Step Functions policy for Lambda invocation
resource "aws_iam_role_policy" "step_functions_lambda" {
  name = "${local.resource_prefix}-step-functions-lambda"
  role = aws_iam_role.step_functions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = [
          "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${local.resource_prefix}-*"
        ]
      }
    ]
  })
}

# Step Functions policy for CloudWatch Logs
resource "aws_iam_role_policy" "step_functions_logs" {
  name = "${local.resource_prefix}-step-functions-logs"
  role = aws_iam_role.step_functions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = [
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/vendedlogs/states/${local.resource_prefix}-*:*"
        ]
      }
    ]
  })
}

# Step Functions policy for X-Ray tracing
resource "aws_iam_role_policy" "step_functions_xray" {
  name = "${local.resource_prefix}-step-functions-xray"
  role = aws_iam_role.step_functions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords"
        ]
        Resource = ["*"]
      }
    ]
  })
}
