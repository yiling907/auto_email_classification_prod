# Lambda module - Deploy all Lambda functions

locals {
  resource_prefix = "${var.project_name}-${var.environment}"
  lambda_source_path = "${path.root}/../lambda"
}

# Data source to package Lambda functions
data "archive_file" "email_parser" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/email_parser"
  output_path = "${path.module}/builds/email_parser.zip"
}

data "archive_file" "rag_ingestion" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/rag_ingestion"
  output_path = "${path.module}/builds/rag_ingestion.zip"
}

data "archive_file" "rag_retrieval" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/rag_retrieval"
  output_path = "${path.module}/builds/rag_retrieval.zip"
}

data "archive_file" "claude_response" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/claude_response"
  output_path = "${path.module}/builds/claude_response.zip"
}

data "archive_file" "classify_intent" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/classify_intent"
  output_path = "${path.module}/builds/classify_intent.zip"
}

data "archive_file" "evaluation_metrics" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/evaluation_metrics"
  output_path = "${path.module}/builds/evaluation_metrics.zip"
}

# Email Parser Lambda
resource "aws_lambda_function" "email_parser" {
  filename         = data.archive_file.email_parser.output_path
  function_name    = "${local.resource_prefix}-email-parser"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 60
  memory_size     = 512
  source_code_hash = data.archive_file.email_parser.output_base64sha256

  environment {
    variables = {
      EMAIL_TABLE_NAME = var.email_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-email-parser" })
}

resource "aws_cloudwatch_log_group" "email_parser" {
  name              = "/aws/lambda/${aws_lambda_function.email_parser.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# RAG Ingestion Lambda
resource "aws_lambda_function" "rag_ingestion" {
  filename         = data.archive_file.rag_ingestion.output_path
  function_name    = "${local.resource_prefix}-rag-ingestion"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 300  # 5 minutes for processing documents
  memory_size     = 1024
  source_code_hash = data.archive_file.rag_ingestion.output_base64sha256

  environment {
    variables = {
      EMBEDDINGS_TABLE_NAME = var.embeddings_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-rag-ingestion" })
}

resource "aws_cloudwatch_log_group" "rag_ingestion" {
  name              = "/aws/lambda/${aws_lambda_function.rag_ingestion.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# RAG Retrieval Lambda
resource "aws_lambda_function" "rag_retrieval" {
  filename         = data.archive_file.rag_retrieval.output_path
  function_name    = "${local.resource_prefix}-rag-retrieval"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 60
  memory_size     = 512
  source_code_hash = data.archive_file.rag_retrieval.output_base64sha256

  environment {
    variables = {
      EMBEDDINGS_TABLE_NAME = var.embeddings_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-rag-retrieval" })
}

resource "aws_cloudwatch_log_group" "rag_retrieval" {
  name              = "/aws/lambda/${aws_lambda_function.rag_retrieval.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Claude Response Lambda
resource "aws_lambda_function" "claude_response" {
  filename         = data.archive_file.claude_response.output_path
  function_name    = "${local.resource_prefix}-claude-response"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 180  # 3 minutes: primary model call + evaluator model call
  memory_size     = 1024
  source_code_hash = data.archive_file.claude_response.output_base64sha256

  environment {
    variables = {
      EMAIL_TABLE_NAME         = var.email_table_name
      MODEL_METRICS_TABLE_NAME = var.model_metrics_table_name
      EVALUATOR_MODEL_ID       = "anthropic.claude-3-haiku-20240307-v1:0"
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-claude-response" })
}

resource "aws_cloudwatch_log_group" "claude_response" {
  name              = "/aws/lambda/${aws_lambda_function.claude_response.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Multi-LLM Inference Lambda
resource "aws_lambda_function" "classify_intent" {
  filename         = data.archive_file.classify_intent.output_path
  function_name    = "${local.resource_prefix}-multi-llm-inference"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 180  # 3 minutes for parallel model calls
  memory_size     = 1024
  source_code_hash = data.archive_file.classify_intent.output_base64sha256

  environment {
    variables = {
      MODEL_METRICS_TABLE_NAME = var.model_metrics_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-multi-llm-inference" })
}

resource "aws_cloudwatch_log_group" "classify_intent" {
  name              = "/aws/lambda/${aws_lambda_function.classify_intent.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Evaluation Metrics Lambda
resource "aws_lambda_function" "evaluation_metrics" {
  filename         = data.archive_file.evaluation_metrics.output_path
  function_name    = "${local.resource_prefix}-evaluation-metrics"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 60
  memory_size     = 512
  source_code_hash = data.archive_file.evaluation_metrics.output_base64sha256

  environment {
    variables = {
      MODEL_METRICS_TABLE_NAME = var.model_metrics_table_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-evaluation-metrics" })
}

resource "aws_cloudwatch_log_group" "evaluation_metrics" {
  name              = "/aws/lambda/${aws_lambda_function.evaluation_metrics.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Data source to package API handler Lambda
data "archive_file" "api_handlers" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/api_handlers"
  output_path = "${path.module}/builds/api_handlers.zip"
}

# API Handlers Lambda (for dashboard API)
resource "aws_lambda_function" "api_handlers" {
  filename         = data.archive_file.api_handlers.output_path
  function_name    = "${local.resource_prefix}-api-handlers"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 30
  memory_size     = 512
  source_code_hash = data.archive_file.api_handlers.output_base64sha256

  environment {
    variables = {
      EMAIL_TABLE_NAME                  = var.email_table_name
      MODEL_METRICS_TABLE_NAME          = var.model_metrics_table_name
      EMBEDDINGS_TABLE_NAME             = var.embeddings_table_name
      EVALUATION_METRICS_FUNCTION_NAME  = aws_lambda_function.evaluation_metrics.function_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-api-handlers" })
}

resource "aws_cloudwatch_log_group" "api_handlers" {
  name              = "/aws/lambda/${aws_lambda_function.api_handlers.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# S3 trigger for RAG ingestion (when new documents are uploaded)
resource "aws_lambda_permission" "allow_s3_rag_ingestion" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.rag_ingestion.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = "arn:aws:s3:::${var.knowledge_base_bucket_name}"
}

# S3 trigger for email parser (when new emails are uploaded)
resource "aws_lambda_permission" "allow_s3_email_parser" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.email_parser.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = "arn:aws:s3:::${var.email_bucket_name}"
}

# Gmail IMAP Poller Lambda (replaces SES email receiver)
data "archive_file" "gmail_imap_poller" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/gmail_imap_poller"
  output_path = "${path.module}/builds/gmail_imap_poller.zip"
}

resource "aws_lambda_function" "gmail_imap_poller" {
  filename         = data.archive_file.gmail_imap_poller.output_path
  function_name    = "${local.resource_prefix}-gmail-imap-poller"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 120  # 2 minutes for IMAP connection and processing
  memory_size     = 256
  source_code_hash = data.archive_file.gmail_imap_poller.output_base64sha256

  environment {
    variables = {
      GMAIL_ADDRESS       = var.gmail_address
      GMAIL_APP_PASSWORD  = var.gmail_app_password
      S3_BUCKET          = var.email_bucket_name
      STATE_MACHINE_ARN  = var.state_machine_arn
      IMAP_SERVER        = var.imap_server
      MARK_AS_READ       = var.mark_emails_as_read
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-gmail-imap-poller" })
}

resource "aws_cloudwatch_log_group" "gmail_imap_poller" {
  name              = "/aws/lambda/${aws_lambda_function.gmail_imap_poller.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# REMOVED: Email Receiver Lambda (SES → SNS → Lambda)
# Email receiving is now handled by Gmail IMAP poller
# Uncomment below if you want to switch back to SES receiving:
#
# data "archive_file" "email_receiver" {
#   type        = "zip"
#   source_dir  = "${local.lambda_source_path}/email_receiver"
#   output_path = "${path.module}/builds/email_receiver.zip"
# }
#
# resource "aws_lambda_function" "email_receiver" {
#   filename         = data.archive_file.email_receiver.output_path
#   function_name    = "${local.resource_prefix}-email-receiver"
#   role            = var.lambda_execution_role_arn
#   handler         = "lambda_function.lambda_handler"
#   runtime         = var.lambda_runtime
#   timeout         = 60
#   memory_size     = 512
#   source_code_hash = data.archive_file.email_receiver.output_base64sha256
#
#   environment {
#     variables = {
#       STATE_MACHINE_ARN = var.state_machine_arn
#       EMAIL_BUCKET_NAME = var.email_bucket_name
#     }
#   }
#
#   tags = merge(var.tags, { Name = "${local.resource_prefix}-email-receiver" })
# }
#
# resource "aws_cloudwatch_log_group" "email_receiver" {
#   name              = "/aws/lambda/${aws_lambda_function.email_receiver.function_name}"
#   retention_in_days = var.log_retention_days
#   tags              = var.tags
# }

# Bedrock Evaluation Lambda
data "archive_file" "bedrock_evaluation" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/bedrock_evaluation"
  output_path = "${path.module}/builds/bedrock_evaluation.zip"
}

resource "aws_lambda_function" "bedrock_evaluation" {
  filename         = data.archive_file.bedrock_evaluation.output_path
  function_name    = "${local.resource_prefix}-bedrock-evaluation"
  role             = var.lambda_execution_role_arn
  handler          = "lambda_function.lambda_handler"
  runtime          = var.lambda_runtime
  timeout          = 300  # 5 min — submitting 6 jobs + S3 uploads
  memory_size      = 512
  source_code_hash = data.archive_file.bedrock_evaluation.output_base64sha256

  environment {
    variables = {
      MODEL_METRICS_TABLE_NAME = var.model_metrics_table_name
      KNOWLEDGE_BASE_BUCKET    = var.knowledge_base_bucket_name
      LOGS_BUCKET              = var.logs_bucket_name
      BEDROCK_EVAL_ROLE_ARN    = var.bedrock_eval_role_arn
      AWS_ACCOUNT_ID           = var.aws_account_id
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-bedrock-evaluation" })
}

resource "aws_cloudwatch_log_group" "bedrock_evaluation" {
  name              = "/aws/lambda/${aws_lambda_function.bedrock_evaluation.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Data source to package Email Sender Lambda
data "archive_file" "email_sender" {
  type        = "zip"
  source_dir  = "${local.lambda_source_path}/email_sender"
  output_path = "${path.module}/builds/email_sender.zip"
}

# Email Sender Lambda (sends responses via SES)
resource "aws_lambda_function" "email_sender" {
  filename         = data.archive_file.email_sender.output_path
  function_name    = "${local.resource_prefix}-email-sender"
  role            = var.lambda_execution_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = 30
  memory_size     = 256
  source_code_hash = data.archive_file.email_sender.output_base64sha256

  environment {
    variables = {
      EMAIL_TABLE_NAME = var.email_table_name
      SENDER_EMAIL     = var.sender_email
      SENDER_NAME      = var.sender_name
    }
  }

  tags = merge(var.tags, { Name = "${local.resource_prefix}-email-sender" })
}

resource "aws_cloudwatch_log_group" "email_sender" {
  name              = "/aws/lambda/${aws_lambda_function.email_sender.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}
